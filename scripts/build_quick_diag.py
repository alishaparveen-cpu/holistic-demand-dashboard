#!/usr/bin/env python3
"""Build data_quick_diag.json — Quick-Diagnostic data derived from the MASTER DEMAND matched files.

Single source of truth: master demand (the L2-matched builders). This consolidates them into the
per-clinic schema weekly-diagnostic.html consumes, with THREE funnel variants per clinic:
  sc  = Screening Calls (demand)   fu = Follow-ups (ops)   all = combined (sc + fu)

Inputs (all already reconciled to L2):
  data_sc_bookings.json · data_fu_bookings.json · data_d2p_econ.json · data_fu_econ.json
  data_availability.json · data_source_recon.json (slug↔City|Locality map, city/tier)
Output per clinic (slug): {city, sc/fu/all:{bookings{total,new_tw,new_old,rebook,relapse},
  done{booked,done,book_done_pct,by_cat{SH,STI,MH,Other}}, availability{...}, velocity{...}, by_doctor{}}}

Run: python3 scripts/build_quick_diag.py   (pure local — no DB)
"""
import os, json, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def L(f): return json.load(open(os.path.join(ROOT, f)))

SCB, FUB = L("data_sc_bookings.json"), L("data_fu_bookings.json")
SCE, FUE = L("data_d2p_econ.json"), L("data_fu_econ.json")
AV, REC = L("data_availability.json"), L("data_source_recon.json")

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

# category rollup (finer diagnoses -> SH/STI/MH/Other)
ROLL = {"SH": ["ED+", "PE+", "ED+PE+", "LSD", "DE", "DYS", "VGS", "FSAD", "AORG"],
        "STI": ["STI"], "MH": ["MH", "PA", "CM"], "Other": ["NOS", "oth"]}

def bk_get(cube, key, field):
    c = cube["clinics"].get(key)
    if not c or field not in c: return Z()
    return remap(c[field], cube["_meta"]["weeks"])

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

def rev_block(cube, key):
    return {"rev": econ_rev_tot(cube, key), "by_cat": {roll: econ_rev_cat(cube, key, codes) for roll, codes in ROLL.items()}}

def purch_block(cube, key):
    return {"total": econ_tot(cube, key, "purchased"), "by_cat": by_cat_block(cube, key, "purchased")}

def avail_block(key):
    c = AV["clinics"].get(key)
    if not c:
        return {"active_days": Z(), "wday_days": Z(), "wend_days": Z(), "avail_hours": Z(), "hours": Z()}
    g = lambda f: remap(c.get(f, []), AV["_meta"]["weeks"])
    return {"active_days": g("active_days"), "wday_days": g("wkday_days"), "wend_days": g("wkend_days"),
            "avail_hours": g("opened_hrs"), "hours": g("net_sc_hrs")}

def doctors_block(bcube, ecube, key):
    out = {}
    bc = (bcube["clinics"].get(key) or {}).get("by_doctor", {})
    ec = (ecube["clinics"].get(key) or {}).get("by_doctor", {})
    for dr in set(bc) | set(ec):
        b = bc.get(dr, {})
        e = ec.get(dr, {})
        booked = remap(b.get("booked", []), bcube["_meta"]["weeks"]) if b else Z()
        done = remap(b.get("done", []), bcube["_meta"]["weeks"]) if b else Z()
        rev = Z()
        if e:
            for f in ("meds_val", "test_val", "ther_val", "cons_val"):
                if f in e: rev = add(rev, remap(e[f], ecube["_meta"]["weeks"]))
        purch = remap(e.get("purchased", []), ecube["_meta"]["weeks"]) if e else Z()
        out[dr] = {"booked": booked, "done": done, "purchased": purch, "rev": rev}
    return out

def velocity_block(booked, av, bkwd, bkwe):
    ad = av["active_days"]; wd = av["wday_days"]; we = av["wend_days"]
    return {"bookings": booked, "wday_days": wd, "wend_days": we,
            "bk_wday": bkwd, "bk_wend": bkwe,   # bookings split by appt day-of-week (sums back to booked)
            "per_active_day": [round(booked[i]/ad[i], 1) if ad[i] else None for i in range(NW)],
            "per_weekday": [round(bkwd[i]/wd[i], 1) if wd[i] else None for i in range(NW)],
            "per_weekend": [round(bkwe[i]/we[i], 1) if we[i] else None for i in range(NW)]}

def variant_sc(key):
    booked = bk_get(SCB, key, "booked"); done = bk_get(SCB, key, "done")
    av = avail_block(key)
    return {"bookings": {"total": booked, "new_tw": bk_get(SCB, key, "ft_same"), "new_old": bk_get(SCB, key, "ft_prev"),
                         "rebook": bk_get(SCB, key, "ret_rebook"), "relapse": bk_get(SCB, key, "ret_return")},
            "done": {"booked": booked, "done": done, "book_done_pct": pct(done, booked), "by_cat": by_cat_block(SCE, key)},
            "revenue": rev_block(SCE, key), "purchased": purch_block(SCE, key),
            "availability": av, "velocity": velocity_block(booked, av, bk_get(SCB, key, "bkwd"), bk_get(SCB, key, "bkwe")),
            "by_doctor": doctors_block(SCB, SCE, key)}

def variant_fu(key):
    booked = bk_get(FUB, key, "booked"); done = bk_get(FUB, key, "done")
    av = avail_block(key)
    return {"bookings": {"total": booked, "new_tw": Z(), "new_old": Z(), "rebook": Z(), "relapse": Z()},
            "done": {"booked": booked, "done": done, "book_done_pct": pct(done, booked), "by_cat": by_cat_block(FUE, key)},
            "revenue": rev_block(FUE, key), "purchased": purch_block(FUE, key),
            "availability": av, "velocity": velocity_block(booked, av, bk_get(FUB, key, "bkwd"), bk_get(FUB, key, "bkwe")),
            "by_doctor": doctors_block(FUB, FUE, key)}

def merge_variant(a, b):
    booked = add(a["bookings"]["total"], b["bookings"]["total"])
    done = add(a["done"]["done"], b["done"]["done"])
    bc = {roll: add(a["done"]["by_cat"][roll], b["done"]["by_cat"][roll]) for roll in ROLL}
    dr = {}
    for d in set(a["by_doctor"]) | set(b["by_doctor"]):
        x = a["by_doctor"].get(d, {"booked": Z(), "done": Z(), "purchased": Z(), "rev": Z()})
        y = b["by_doctor"].get(d, {"booked": Z(), "done": Z(), "purchased": Z(), "rev": Z()})
        dr[d] = {k: add(x[k], y[k]) for k in ("booked", "done", "purchased", "rev")}
    rev = {"rev": add(a["revenue"]["rev"], b["revenue"]["rev"]),
           "by_cat": {roll: add(a["revenue"]["by_cat"][roll], b["revenue"]["by_cat"][roll]) for roll in ROLL}}
    pur = {"total": add(a["purchased"]["total"], b["purchased"]["total"]),
           "by_cat": {roll: add(a["purchased"]["by_cat"][roll], b["purchased"]["by_cat"][roll]) for roll in ROLL}}
    bkwd = add(a["velocity"]["bk_wday"], b["velocity"]["bk_wday"])   # SC + FU weekday bookings
    bkwe = add(a["velocity"]["bk_wend"], b["velocity"]["bk_wend"])   # SC + FU weekend bookings
    return {"bookings": {"total": booked, "new_tw": a["bookings"]["new_tw"], "new_old": a["bookings"]["new_old"],
                         "rebook": a["bookings"]["rebook"], "relapse": a["bookings"]["relapse"]},
            "done": {"booked": booked, "done": done, "book_done_pct": pct(done, booked), "by_cat": bc},
            "revenue": rev, "purchased": pur,
            "availability": a["availability"], "velocity": velocity_block(booked, a["availability"], bkwd, bkwe), "by_doctor": dr}


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
        sc = variant_sc(key); fu = variant_fu(key)
        clinics[slug] = {"city": city, "tier": tier.get(city, "?"),
                         "sc": sc, "fu": fu, "all": merge_variant(sc, fu)}
    wl = [datetime.date.fromisoformat(w).strftime("%d %b") for w in WEEKS]
    out = {"weeks": WEEKS, "week_labels": wl, "source": "master-demand matched files (SC+FU+econ+avail)",
           "clinics": clinics}
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
