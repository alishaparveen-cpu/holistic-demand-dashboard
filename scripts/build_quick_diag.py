#!/usr/bin/env python3
"""Build data_quick_diag.json — Quick-Diagnostic data derived from the MASTER DEMAND matched files.

Single source of truth: master demand (the L2-matched builders). This consolidates them into the
per-clinic schema weekly-diagnostic.html consumes, with THREE funnel variants per clinic:
  sc  = Screening Calls (demand)   fu = Follow-ups (ops)   all = combined (sc + fu)

Inputs (all already reconciled to L2):
  data_sc_bookings.json · data_fu_bookings.json · data_d2p_econ.json · data_fu_econ.json
  data_availability.json · data_source_recon.json (slug↔City|Locality map, city/tier)
Output per clinic (slug): {city, sc/fu/all:{bookings{total,new_tw,new_old,rebook,relapse},
  done{booked,done,book_done_pct,by_cat{MH,ED+,ED+PE+,PE+,STI,Oth,NOS}}, availability{...}, velocity{...}, by_doctor{}}}

Run: python3 scripts/build_quick_diag.py   (pure local — no DB)
"""
import os, json, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def L(f): return json.load(open(os.path.join(ROOT, f)))

SCB, FUB = L("data_sc_bookings.json"), L("data_fu_bookings.json")
SCE, FUE = L("data_d2p_econ.json"), L("data_fu_econ.json")
AV, REC = L("data_availability.json"), L("data_source_recon.json")
AVD = L("data_avail_doctor.json")   # per-DOCTOR days-attended/rostered (build_avail_doctor.py) → fills by_doctor availability
_avd_norm = lambda n: (n or "").replace("\xa0", " ").strip()

# ── target week axis: last 26 complete weeks (Mon start, fully elapsed) ──
today = datetime.date.today()
allw = sorted(set(SCB["_meta"]["weeks"]))
full = [w for w in allw if datetime.date.fromisoformat(w) + datetime.timedelta(days=7) <= today]
WEEKS = full[-26:]
NW = len(WEEKS)
widx = {w: i for i, w in enumerate(WEEKS)}
Z = lambda: [0]*NW

def remap(arr, src_weeks):
    o = Z()
    for i, w in enumerate(src_weeks):
        j = widx.get(w)
        if j is not None and i < len(arr):
            o[j] = arr[i] or 0
    return o

def add(a, b): return [a[i]+b[i] for i in range(NW)]
def pct(n, d): return [round(100*n[i]/d[i]) if d[i] else None for i in range(NW)]

# slug -> "City|Locality"
disp = REC["_meta"].get("display", {})
slug2key = {}
for slug, s in disp.items():
    p = str(s).split(" · ")
    if len(p) >= 2:
        slug2key[slug] = p[-1] + "|" + " · ".join(p[:-1])
tier = REC["_meta"].get("city_tier", {})

# category rollup (finer diagnoses -> the 7 city-head buckets: MH·ED+·ED+PE+·PE+·STI·Oth·NOS).
# ED/PE keep their own buckets (what city heads track); the other named sexual-health conditions (LSD/DE/DYS/VGS/FSAD/AORG)
# keep their own sub-cat too so they roll to SH (not Other) in the UI. Only the genuine catch-all 'oth' → Oth; NOS stands alone.
ROLL = {"MH": ["MH"], "PA": ["PA"], "CM": ["CM"], "ED+": ["ED+"], "ED+PE+": ["ED+PE+"], "PE+": ["PE+"], "STI": ["STI"],
        "LSD": ["LSD"], "DE": ["DE"], "DYS": ["DYS"], "VGS": ["VGS"], "FSAD": ["FSAD"], "AORG": ["AORG"],
        "Oth": ["oth"], "NOS": ["NOS"]}
# MH sub-codes: MH=Mental Health Concern · PA=Porn Addiction · CM=Compulsive Masturbation (grouped as MH in the UI tree)

def bk_get(cube, key, field):
    c = cube["clinics"].get(key)
    if not c or field not in c: return Z()
    return remap(c[field], cube["_meta"]["weeks"])

def bk_sum(cube, key, *fields):   # sum of several fields (e.g. older-week = ft_prev + ft_nolead)
    arrs = [bk_get(cube, key, f) for f in fields]
    return [sum(x) for x in zip(*arrs)] if arrs else Z()

def econ_cat(cube, key, cat_codes, field):
    c = cube["clinics"].get(key)
    if not c: return Z()
    o = Z()
    bycat = c.get("by_cat", {})
    for code in cat_codes:
        cc = bycat.get(code)
        if cc and field in cc:
            o = add(o, remap(cc[field], cube["_meta"]["weeks"]))
    return o

def econ_tot(cube, key, field):
    c = cube["clinics"].get(key)
    if not c or field not in c: return Z()
    return remap(c[field], cube["_meta"]["weeks"])

def by_cat_block(cube, key, field="done"):
    return {roll: econ_cat(cube, key, codes, field) for roll, codes in ROLL.items()}

def by_cat_source_block(cube, key):   # done × rolled-category × SOURCE — the EXACT cross (done only), from d2p econ by_cat_source
    c = cube["clinics"].get(key)
    if not c: return {}
    wks = cube["_meta"]["weeks"]; bcs = c.get("by_cat_source") or {}
    out = {}
    for roll, codes in ROLL.items():
        srcmap = {}
        for code in codes:
            for src, arr in (bcs.get(code) or {}).items():
                srcmap[src] = add(srcmap.get(src, Z()), remap(arr, wks))
        keep = {src: a for src, a in srcmap.items() if any(a)}
        if keep: out[roll] = keep
    return out

def econ_rev_tot(cube, key):
    o = Z()
    for f in ("meds_val", "test_val", "ther_val", "cons_val"):
        o = add(o, econ_tot(cube, key, f))
    return o

def econ_rev_cat(cube, key, codes):
    o = Z()
    for f in ("meds_val", "test_val", "ther_val", "cons_val"):
        o = add(o, econ_cat(cube, key, codes, f))
    return o

# collection view (status='paid'): same done-week grain, only invoices actually paid
def econ_rev_tot_paid(cube, key):
    o = Z()
    for f in ("meds_val_paid", "test_val_paid", "ther_val_paid", "cons_val_paid"):
        o = add(o, econ_tot(cube, key, f))
    return o

def econ_rev_cat_paid(cube, key, codes):
    o = Z()
    for f in ("meds_val_paid", "test_val_paid", "ther_val_paid", "cons_val_paid"):
        o = add(o, econ_cat(cube, key, codes, f))
    return o

def line_block(cube, key, field):   # one revenue line (meds/test/ther/cons): total + by-category, for per-line RPC
    return {"tot": econ_tot(cube, key, field), "by_cat": {roll: econ_cat(cube, key, codes, field) for roll, codes in ROLL.items()}}

def rev_block(cube, key):
    b = {"rev": econ_rev_tot(cube, key), "by_cat": {roll: econ_rev_cat(cube, key, codes) for roll, codes in ROLL.items()}}
    for nm, field in (("meds", "meds_val"), ("test", "test_val"), ("ther", "ther_val"), ("cons", "cons_val")):
        b[nm] = line_block(cube, key, field)
    pm, pt, ph = econ_tot(cube, key, "pres_meds_val"), econ_tot(cube, key, "pres_test_val"), econ_tot(cube, key, "pres_ther_val")   # billed value incl unpaid, per line (for per-line Pres AOV / prescribe value)
    b["pres_meds"], b["pres_test"], b["pres_ther"] = pm, pt, ph
    b["pres_val"] = add(add(pm, pt), ph)   # overall billed product value = sum of the three lines (Pres AOV = pres_val / done)
    # ⑥ collection view (paid-only, same done-week grain): Revenue(paid)/RPC(paid)/AOV(paid) + category drill
    b["rev_paid"] = econ_rev_tot_paid(cube, key)
    b["by_cat_paid"] = {roll: econ_rev_cat_paid(cube, key, codes) for roll, codes in ROLL.items()}
    b["cons_paid"] = econ_tot(cube, key, "cons_val_paid")   # paid consult fee (so AOV-collected = products-only = rev_paid - cons_paid)
    return b

def purch_block(cube, key):
    return {"total": econ_tot(cube, key, "purchased"), "by_cat": by_cat_block(cube, key, "purchased"),
            "paid": econ_tot(cube, key, "purchased_paid"), "by_cat_paid": by_cat_block(cube, key, "purchased_paid")}

# ── national ONLINE telehealth, per SC/FU/All variant (from the online cubes; single 'Online|Online' key) ──
try:
    SCBO, FUBO = L("data_sc_bookings_online.json"), L("data_fu_bookings_online.json")
    SCEO, FUEO = L("data_d2p_econ_online.json"), L("data_fu_econ_online.json")
except Exception:
    SCBO = FUBO = SCEO = FUEO = None
OKEY = "Online|Online"
def online_variant(bcube, ecube):
    booked = bk_get(bcube, OKEY, "booked"); done = bk_get(bcube, OKEY, "done")
    return {"bookings": {"total": booked, "nat": booked, "city": booked, "new_tw": Z(), "new_old": Z(), "rebook": Z(), "relapse": Z(),
                         "by_source": source_block(bcube, OKEY) if "by_source" in (bcube["clinics"].get(OKEY) or {}) else {}},
            "done": {"booked": booked, "booked_nat": booked, "booked_city": booked, "done": done, "done_nat": done, "done_city": done, "book_done_pct": pct(done, booked), "by_cat": by_cat_block(ecube, OKEY)},
            "revenue": rev_block(ecube, OKEY), "purchased": purch_block(ecube, OKEY)}
def online_all(a, b):
    bk = add(a["bookings"]["total"], b["bookings"]["total"]); dn = add(a["done"]["done"], b["done"]["done"])
    rev = {"rev": add(a["revenue"]["rev"], b["revenue"]["rev"]),
           "by_cat": {r: add(a["revenue"]["by_cat"][r], b["revenue"]["by_cat"][r]) for r in ROLL}}
    for nm in ("meds", "test", "ther", "cons"):
        rev[nm] = {"tot": add(a["revenue"][nm]["tot"], b["revenue"][nm]["tot"]),
                   "by_cat": {r: add(a["revenue"][nm]["by_cat"][r], b["revenue"][nm]["by_cat"][r]) for r in ROLL}}
    for pk in ("pres_val", "pres_meds", "pres_test", "pres_ther"):
        rev[pk] = add(a["revenue"].get(pk, Z()), b["revenue"].get(pk, Z()))
    rev["rev_paid"] = add(a["revenue"].get("rev_paid", Z()), b["revenue"].get("rev_paid", Z()))
    rev["cons_paid"] = add(a["revenue"].get("cons_paid", Z()), b["revenue"].get("cons_paid", Z()))
    rev["by_cat_paid"] = {r: add(a["revenue"].get("by_cat_paid", {}).get(r, Z()), b["revenue"].get("by_cat_paid", {}).get(r, Z())) for r in ROLL}
    return {"bookings": {"total": bk, "nat": bk, "city": bk, "new_tw": Z(), "new_old": Z(), "rebook": Z(), "relapse": Z(), "by_source": a["bookings"].get("by_source", {})},
            "done": {"booked": bk, "booked_nat": bk, "booked_city": bk, "done": dn, "done_nat": dn, "done_city": dn, "book_done_pct": pct(dn, bk),
                     "by_cat": {r: add(a["done"]["by_cat"][r], b["done"]["by_cat"][r]) for r in ROLL}},
            "revenue": rev,
            "purchased": {"total": add(a["purchased"]["total"], b["purchased"]["total"]),
                          "by_cat": {r: add(a["purchased"]["by_cat"][r], b["purchased"]["by_cat"][r]) for r in ROLL},
                          "paid": add(a["purchased"].get("paid", Z()), b["purchased"].get("paid", Z())),
                          "by_cat_paid": {r: add(a["purchased"].get("by_cat_paid", {}).get(r, Z()), b["purchased"].get("by_cat_paid", {}).get(r, Z())) for r in ROLL}}}
def online_block():
    if not SCBO: return None
    osc = online_variant(SCBO, SCEO); ofu = online_variant(FUBO, FUEO)
    return {"sc": osc, "fu": ofu, "all": online_all(osc, ofu)}

def avail_block(key, slug=None):
    c = AV["clinics"].get(key)
    base = {"active_days": Z(), "wday_days": Z(), "wend_days": Z(), "avail_hours": Z(), "hours": Z(), "sc_slots": Z(), "rpt_slots": Z(),
            "attend_days": Z(), "attend_wday": Z(), "attend_wend": Z()}
    if c:
        g = lambda f: remap(c.get(f, []), AV["_meta"]["weeks"])
        base = {"active_days": g("active_days"), "wday_days": g("wkday_days"), "wend_days": g("wkend_days"),
                "avail_hours": g("opened_hrs"), "hours": g("net_sc_hrs"), "sc_slots": g("net_sc_slots"), "rpt_slots": g("net_rpt_slots"),
                "attend_days": g("attend_days"), "attend_wday": g("attend_wkday"), "attend_wend": g("attend_wkend")}
    ar = (REC["clinics"].get(slug, {}) if slug else {}).get("avail_roster")   # ops-roster hours (matches the Macro sheet)
    if ar:
        rw = REC["_meta"]["weeks"]; rg = lambda f: remap(ar.get(f, []), rw)
        base.update({"opened_ash": rg("after_shrink"), "rostered_hrs": rg("opened"), "shrink_hrs": rg("shrink"),
                     "net_sc_hrs_r": rg("sc_net"), "net_rpt_hrs": rg("fu_net"), "net_avail_hrs": rg("net_avail"), "dead_hrs": rg("dead")})
    # rostered/shrink HOURS come from the ops-roster cube above (opened/shrink → rostered−shrink = after_shrink = opened_ash, matches the Macro sheet).
    # Fall back to the per-doctor block sum ONLY for weeks the ops-roster grid hasn't reached (the per-doctor sum is a GROSS over-count when avail_roster exists — that was the bug).
    avd = AVD["clinics"].get(slug) if slug else None
    if avd:
        aw = AVD["_meta"]["weeks"]; oh = Z(); sh = Z()
        for dd in avd["by_doctor"].values():
            oh = add(oh, remap(dd.get("rostered_hrs", []), aw)); sh = add(sh, remap(dd.get("shrink_hrs", []), aw))
        base["rostered_hrs"] = [base.get("rostered_hrs", Z())[i] or oh[i] for i in range(NW)]
        base["shrink_hrs"] = [base.get("shrink_hrs", Z())[i] or sh[i] for i in range(NW)]
    # opened / net-SC hours: prefer the ops-roster cube (REC, matches the Macro sheet); fall back to the availability cube (AV, current)
    # for weeks the ops-roster grid hasn't reached yet — same realized-roster methodology, so no discontinuity. (net-Rpt + dead-time exist only in REC.)
    if "opened_ash" in base: base["opened_ash"] = [base["opened_ash"][i] or base["avail_hours"][i] for i in range(NW)]
    if "net_sc_hrs_r" in base: base["net_sc_hrs_r"] = [base["net_sc_hrs_r"][i] or base["hours"][i] for i in range(NW)]
    # ROSTER-LAG GUARD: roster-only hours (rostered/shrink/net-Rpt/dead) don't exist past the ops-roster grid's
    # newest realized week (roster realization lags ~1wk). Null them beyond that edge so the immature newest week
    # renders blank — NOT the gross per-doctor over-count (rostered/shrink) or a false −99% zero (net-Rpt/dead).
    rec_edge = max((widx[w] for w in REC["_meta"]["weeks"] if w in widx), default=NW - 1)
    for f in ("rostered_hrs", "shrink_hrs", "net_rpt_hrs", "dead_hrs", "net_avail_hrs"):
        if f in base:
            base[f] = [base[f][i] if i <= rec_edge else None for i in range(NW)]
    return base

def avail_doctor_block(slug, dr):
    """Per-doctor days-attended/rostered for this clinic, name-matched (nbsp-normalised), remapped to WEEKS.
    Returns None when the doctor has no roster/attendance at this clinic (they book here but attend elsewhere)."""
    cl = AVD["clinics"].get(slug)
    if not cl: return None
    bd = cl["by_doctor"]; want = _avd_norm(dr)
    src = bd.get(dr) or next((v for k, v in bd.items() if _avd_norm(k) == want), None)
    if not src: return None
    aw = AVD["_meta"]["weeks"]; g = lambda f: remap(src.get(f, []), aw)
    return {"active_days": g("active_days"), "wday_days": g("wday_days"), "wend_days": g("wend_days"),
            "attend_days": g("attend_days"), "attend_wday": g("attend_wday"), "attend_wend": g("attend_wend"),
            "rostered_hrs": g("rostered_hrs"), "shrink_hrs": g("shrink_hrs")}

def doctors_block(bcube, ecube, key, slug=None):
    out = {}
    bc = (bcube["clinics"].get(key) or {}).get("by_doctor", {})
    ec = (ecube["clinics"].get(key) or {}).get("by_doctor", {})
    for dr in set(bc) | set(ec):
        b = bc.get(dr, {})
        e = ec.get(dr, {})
        booked = remap(b.get("booked", []), bcube["_meta"]["weeks"]) if b else Z()
        done = remap(b.get("done", []), bcube["_meta"]["weeks"]) if b else Z()
        lines = {"meds": Z(), "test": Z(), "ther": Z(), "cons": Z()}   # per-doctor product-line revenue (for doctor-level RPC by line)
        if e:
            for f, k in (("meds_val", "meds"), ("test_val", "test"), ("ther_val", "ther"), ("cons_val", "cons")):
                if f in e: lines[k] = remap(e[f], ecube["_meta"]["weeks"])
        rev = add(add(lines["meds"], lines["test"]), add(lines["ther"], lines["cons"]))
        purch = remap(e.get("purchased", []), ecube["_meta"]["weeks"]) if e else Z()
        newp = Z()   # per-doctor NEW patients = fresh + carry-in (ft_same + ft_prev + ft_nolead)
        if b:
            for f in ("ft_same", "ft_prev", "ft_nolead"):
                if f in b: newp = add(newp, remap(b[f], bcube["_meta"]["weeks"]))
        catdone = {roll: Z() for roll in ROLL}   # per-doctor DONE by category (rolled to CATS buckets)
        ecd = (e.get("cat_done") or {}) if e else {}
        if ecd:
            for roll, codes in ROLL.items():
                for code in codes:
                    if code in ecd: catdone[roll] = add(catdone[roll], remap(ecd[code], ecube["_meta"]["weeks"]))
        presL = {"pres_meds": Z(), "pres_test": Z(), "pres_ther": Z()}   # per-doctor billed value per line (Pres AOV / prescribe value)
        if e:
            for f, k in (("pres_meds_val", "pres_meds"), ("pres_test_val", "pres_test"), ("pres_ther_val", "pres_ther")):
                if f in e: presL[k] = remap(e[f], ecube["_meta"]["weeks"])
        presv = add(add(presL["pres_meds"], presL["pres_test"]), presL["pres_ther"])
        rec = {"booked": booked, "done": done, "purchased": purch, "rev": rev, "new": newp, "cat_done": catdone,
               "meds": lines["meds"], "test": lines["test"], "ther": lines["ther"], "cons": lines["cons"],
               "pres_val": presv, "pres_meds": presL["pres_meds"], "pres_test": presL["pres_test"], "pres_ther": presL["pres_ther"]}
        av = avail_doctor_block(slug, dr) if slug else None
        if av: rec["availability"] = av
        out[dr] = rec
    return out

def velocity_block(booked, av, bkwd, bkwe, dnwd=None, dnwe=None):
    ad = av["active_days"]; wd = av["wday_days"]; we = av["wend_days"]
    dnwd = dnwd or Z(); dnwe = dnwe or Z()
    return {"bookings": booked, "wday_days": wd, "wend_days": we,
            "bk_wday": bkwd, "bk_wend": bkwe,   # bookings split by appt day-of-week (sums back to booked)
            "done_wday": dnwd, "done_wend": dnwe,   # done split by appt day-of-week (for done-velocity)
            "per_active_day": [round(booked[i]/ad[i], 1) if ad[i] else None for i in range(NW)],
            "per_weekday": [round(bkwd[i]/wd[i], 1) if wd[i] else None for i in range(NW)],
            "per_weekend": [round(bkwe[i]/we[i], 1) if we[i] else None for i in range(NW)],
            "done_per_weekday": [round(dnwd[i]/wd[i], 1) if wd[i] else None for i in range(NW)],
            "done_per_weekend": [round(dnwe[i]/we[i], 1) if we[i] else None for i in range(NW)]}

def source_block(cube, key):   # bookings+done split by lead source. by_source[src] = {booked, done, +grain-distinct variants}
    c = cube["clinics"].get(key)
    if not c: return {}
    wks = cube["_meta"]["weeks"]; out = {}
    for src, dd in (c.get("by_source") or {}).items():
        if not isinstance(dd, dict): continue
        bk = dd.get("booked") or []
        if not any(bk): continue
        rec = {"booked": remap(bk, wks), "done": remap(dd.get("done") or [], wks)}
        for f in ("booked_nat", "booked_city", "done_nat", "done_city"):
            if dd.get(f) is not None:
                rec[f] = remap(dd.get(f), wks)
        # cross-cut: new (fresh+carry-in) and repeat patients WITHIN each source (from the per-source patient-type splits already in the cube)
        sn = dd.get("ft_same") or []; sp = dd.get("ft_prev") or []; snl = dd.get("ft_nolead") or []; rp = dd.get("repeat") or []
        n = max(len(sn), len(sp), len(snl), len(rp), 0)
        get = lambda a, i: (a[i] if i < len(a) else 0) or 0
        rec["new"] = remap([get(sn, i) + get(sp, i) + get(snl, i) for i in range(n)], wks)
        rec["repeat"] = remap(rp, wks)
        # finer sub-bucket × source (level-3 cross): within fresh / older-week / never-done / relapse, the lead source
        rb = dd.get("ret_rebook") or []; rr = dd.get("ret_return") or []
        rec["fresh"]   = remap(sn, wks)                                              # ft_same
        rec["older"]   = remap([get(sp, i) + get(snl, i) for i in range(n)], wks)     # ft_prev + ft_nolead (carry-in)
        rec["never"]   = remap(rb, wks)                                              # ret_rebook (never completed before)
        rec["relapse"] = remap(rr, wks)                                             # ret_return (done before, booked again)
        out[src] = rec
    return out

def variant_sc(key, slug=None):
    booked = bk_get(SCB, key, "booked"); done = bk_get(SCB, key, "done")
    b_nat = bk_get(SCB, key, "booked_nat"); b_city = bk_get(SCB, key, "booked_city")
    d_nat = bk_get(SCB, key, "done_nat"); d_city = bk_get(SCB, key, "done_city")
    if not any(b_nat): b_nat = booked          # graceful fallback if cube predates grain fields
    if not any(b_city): b_city = booked
    if not any(d_nat): d_nat = done
    if not any(d_city): d_city = done
    av = avail_block(key, slug)
    return {"bookings": {"total": booked, "nat": b_nat, "city": b_city, "new_tw": bk_get(SCB, key, "ft_same"), "new_old": bk_sum(SCB, key, "ft_prev", "ft_nolead"),
                         "no1w": bk_get(SCB, key, "ft_prev_1w"), "no2_4w": bk_get(SCB, key, "ft_prev_2_4w"), "no1_3mo": bk_get(SCB, key, "ft_prev_1_3mo"), "no3mo": bk_get(SCB, key, "ft_prev_3mo"),   # older-lead bookings binned by lead age
                         "rebook": bk_get(SCB, key, "ret_rebook"), "relapse": bk_get(SCB, key, "ret_return"),
                         "by_source": source_block(SCB, key)},
            "done": {"booked": booked, "booked_nat": b_nat, "booked_city": b_city, "done": done, "done_nat": d_nat, "done_city": d_city, "book_done_pct": pct(done, booked), "by_cat": by_cat_block(SCE, key), "by_cat_source": by_cat_source_block(SCE, key),
                     "by_age": {"fresh": bk_get(SCB, key, "done_fresh"), "wk1": bk_get(SCB, key, "done_wk1"), "wk2_4": bk_get(SCB, key, "done_wk2_4"), "mo1_3": bk_get(SCB, key, "done_mo1_3"), "mo3": bk_get(SCB, key, "done_mo3"), "nolead": bk_get(SCB, key, "done_nolead")},   # DONE by lead maturity (done-date pinned, ties to done total)
                     "by_brank": {"1st": bk_get(SCB, key, "done_r1"), "2nd": bk_get(SCB, key, "done_r2"), "3rd": bk_get(SCB, key, "done_r3"), "4pl": bk_get(SCB, key, "done_r4pl")},   # DONE by booking rank
                     "booked_slots": bk_get(SCB, key, "booked_slots"), "done_slots": bk_get(SCB, key, "done_slots"),   # slot level (appointment rows) alongside the distinct-patient booked/done
                     "slot_status": {"COMPLETED": bk_get(SCB, key, "st_completed"), "SCHEDULED": bk_get(SCB, key, "st_scheduled"), "No Show": bk_get(SCB, key, "st_noshow"), "Reschedule": bk_get(SCB, key, "st_reschedule"), "CANCELLED": bk_get(SCB, key, "st_cancelled"), "Others": bk_get(SCB, key, "st_others")}},   # slot outcome breakdown (sums to booked_slots)
            "revenue": rev_block(SCE, key), "purchased": purch_block(SCE, key),
            "availability": av, "velocity": velocity_block(booked, av, bk_get(SCB, key, "bkwd"), bk_get(SCB, key, "bkwe"), bk_get(SCB, key, "done_wkday"), bk_get(SCB, key, "done_wkend")),
            "by_doctor": doctors_block(SCB, SCE, key, slug)}

def variant_fu(key, slug=None):
    booked = bk_get(FUB, key, "booked"); done = bk_get(FUB, key, "done")
    av = avail_block(key, slug)
    return {"bookings": {"total": booked, "nat": booked, "city": booked, "new_tw": Z(), "new_old": Z(), "rebook": Z(), "relapse": Z(), "by_source": {}},
            "done": {"booked": booked, "booked_nat": booked, "booked_city": booked, "done": done, "done_nat": done, "done_city": done, "book_done_pct": pct(done, booked), "by_cat": by_cat_block(FUE, key)},
            "revenue": rev_block(FUE, key), "purchased": purch_block(FUE, key),
            "availability": av, "velocity": velocity_block(booked, av, bk_get(FUB, key, "bkwd"), bk_get(FUB, key, "bkwe"), bk_get(FUB, key, "done_wkday"), bk_get(FUB, key, "done_wkend")),
            "by_doctor": doctors_block(FUB, FUE, key, slug)}

def merge_variant(a, b):
    booked = add(a["bookings"]["total"], b["bookings"]["total"])
    done = add(a["done"]["done"], b["done"]["done"])
    b_nat = add(a["bookings"].get("nat", a["bookings"]["total"]), b["bookings"].get("nat", b["bookings"]["total"]))
    b_city = add(a["bookings"].get("city", a["bookings"]["total"]), b["bookings"].get("city", b["bookings"]["total"]))
    d_nat = add(a["done"].get("done_nat", a["done"]["done"]), b["done"].get("done_nat", b["done"]["done"]))
    d_city = add(a["done"].get("done_city", a["done"]["done"]), b["done"].get("done_city", b["done"]["done"]))
    bc = {roll: add(a["done"]["by_cat"][roll], b["done"]["by_cat"][roll]) for roll in ROLL}
    dr = {}
    for d in set(a["by_doctor"]) | set(b["by_doctor"]):
        blank_dr = {"booked": Z(), "done": Z(), "purchased": Z(), "rev": Z(), "new": Z(), "meds": Z(), "test": Z(), "ther": Z(), "cons": Z()}
        x = a["by_doctor"].get(d, blank_dr)
        y = b["by_doctor"].get(d, blank_dr)
        dr[d] = {k: add(x.get(k, Z()), y.get(k, Z())) for k in ("booked", "done", "purchased", "rev", "new", "meds", "test", "ther", "cons", "pres_val", "pres_meds", "pres_test", "pres_ther")}
        dr[d]["cat_done"] = {roll: add((x.get("cat_done", {}) or {}).get(roll, Z()), (y.get("cat_done", {}) or {}).get(roll, Z())) for roll in ROLL}
        av = x.get("availability") or y.get("availability")   # physical attendance is funnel-independent — keep one, don't sum SC+FU
        if av: dr[d]["availability"] = av
    rev = {"rev": add(a["revenue"]["rev"], b["revenue"]["rev"]),
           "by_cat": {roll: add(a["revenue"]["by_cat"][roll], b["revenue"]["by_cat"][roll]) for roll in ROLL}}
    for nm in ("meds", "test", "ther", "cons"):
        rev[nm] = {"tot": add(a["revenue"][nm]["tot"], b["revenue"][nm]["tot"]),
                   "by_cat": {roll: add(a["revenue"][nm]["by_cat"][roll], b["revenue"][nm]["by_cat"][roll]) for roll in ROLL}}
    for pk in ("pres_val", "pres_meds", "pres_test", "pres_ther"):
        rev[pk] = add(a["revenue"].get(pk, Z()), b["revenue"].get(pk, Z()))
    rev["rev_paid"] = add(a["revenue"].get("rev_paid", Z()), b["revenue"].get("rev_paid", Z()))
    rev["cons_paid"] = add(a["revenue"].get("cons_paid", Z()), b["revenue"].get("cons_paid", Z()))
    rev["by_cat_paid"] = {roll: add(a["revenue"].get("by_cat_paid", {}).get(roll, Z()), b["revenue"].get("by_cat_paid", {}).get(roll, Z())) for roll in ROLL}
    pur = {"total": add(a["purchased"]["total"], b["purchased"]["total"]),
           "by_cat": {roll: add(a["purchased"]["by_cat"][roll], b["purchased"]["by_cat"][roll]) for roll in ROLL},
           "paid": add(a["purchased"].get("paid", Z()), b["purchased"].get("paid", Z())),
           "by_cat_paid": {roll: add(a["purchased"].get("by_cat_paid", {}).get(roll, Z()), b["purchased"].get("by_cat_paid", {}).get(roll, Z())) for roll in ROLL}}
    bkwd = add(a["velocity"]["bk_wday"], b["velocity"]["bk_wday"])   # SC + FU weekday bookings
    bkwe = add(a["velocity"]["bk_wend"], b["velocity"]["bk_wend"])   # SC + FU weekend bookings
    dnwd = add(a["velocity"].get("done_wday", Z()), b["velocity"].get("done_wday", Z()))
    dnwe = add(a["velocity"].get("done_wend", Z()), b["velocity"].get("done_wend", Z()))
    return {"bookings": {"total": booked, "nat": b_nat, "city": b_city, "new_tw": a["bookings"]["new_tw"], "new_old": a["bookings"]["new_old"],
                         "no1w": a["bookings"].get("no1w", Z()), "no2_4w": a["bookings"].get("no2_4w", Z()), "no1_3mo": a["bookings"].get("no1_3mo", Z()), "no3mo": a["bookings"].get("no3mo", Z()),   # lead-age buckets from SC (FU has none)
                         "rebook": a["bookings"]["rebook"], "relapse": a["bookings"]["relapse"], "by_source": a["bookings"].get("by_source", {})},
            "done": {"booked": booked, "booked_nat": b_nat, "booked_city": b_city, "done": done, "done_nat": d_nat, "done_city": d_city, "book_done_pct": pct(done, booked), "by_cat": bc},
            "revenue": rev, "purchased": pur,
            "availability": a["availability"], "velocity": velocity_block(booked, a["availability"], bkwd, bkwe, dnwd, dnwe), "by_doctor": dr}


def main():
    clinics = {}
    keys = set(SCB["clinics"]) | set(FUB["clinics"])
    key2slug = {v: k for k, v in slug2key.items()}
    for key in keys:
        slug = key2slug.get(key)
        if not slug:   # fabricate a slug from the key so nothing is dropped
            city, loc = (key.split("|") + [""])[:2]
            slug = (loc + "_" + city).lower().replace(" ", "_")
        city = key.split("|")[0]
        sc = variant_sc(key, slug); fu = variant_fu(key, slug)
        clinics[slug] = {"city": city, "tier": tier.get(city, "?"),
                         "sc": sc, "fu": fu, "all": merge_variant(sc, fu)}
    wl = [datetime.date.fromisoformat(w).strftime("%d %b") for w in WEEKS]
    out = {"weeks": WEEKS, "week_labels": wl, "source": "master-demand matched files (SC+FU+econ+avail)",
           "clinics": clinics, "online": online_block()}
    json.dump(out, open(os.path.join(ROOT, "data_quick_diag.json"), "w"), separators=(",", ":"))

    # verify: national latest week
    lw = NW-1
    def nat(v, path):
        t = 0
        for c in clinics.values():
            o = c[v]
            for p in path.split("."):
                o = o[p]
            t += o[lw] or 0
        return t
    print(f"data_quick_diag.json · {len(clinics)} clinics · {NW} weeks ({WEEKS[0]}→{WEEKS[-1]})")
    for v in ("sc", "fu", "all"):
        print(f"  {v:4} booked {nat(v,'bookings.total'):5} · done {nat(v,'done.done'):5}")


if __name__ == "__main__":
    main()
