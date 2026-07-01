#!/usr/bin/env python3
"""DEMAND-FIRST backport for the old city/country funnels (data_source_recon.json).

The old funnels credit a completion to the week the COMPLETED SC was created. A patient who
no-shows week-1 and completes after rebooking week-3 was counted done in week-3 (and NOT-done
in week-1) -> the week-1 demand looked lost. Demand-first credits the completion back to the
DEMAND week (the patient's earliest un-credited booking week at that clinic). Reschedules move
earlier; relapses (a fresh SC after a prior completion) match to their OWN later booking week,
so they stay captured as separate demand.

Method: one per-clinic query returns each deduped (patient, week) SC row with status, sub-cat,
source and paid/rev (reusing the EXACT existing category/source/rev logic). In Python we match
each completion to the earliest un-credited booking week <= its completion week, then rebuild
demand-first: bottom.done/purchased/rev, bottom.by_cat, bottom.by_subcat (done/purchased/rev
only; BOOKED is a booking-side field and is left untouched), done_by_source, done_cat_source.

SAFETY: we ALSO rebuild the same fields at completion-week and assert they reproduce the
existing per-clinic totals (done/purchased/rev) within tolerance. If a clinic drifts we skip it
(don't write) and report. Totals are preserved by construction — only the WEEK moves.
Resumable via bottom.demand_first flag. Run: AWS_PROFILE=redshift-data python3 scripts/patch_demand_first.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import patch_subcat as PS          # SUBCASE, run_sql, idx, Z, LO, CATS
import openpyxl
ROOT = PS.ROOT; OUT = os.path.join(ROOT, "data_source_recon.json")
idx = PS.idx; Z = PS.Z; LO = PS.LO; run_sql = PS.run_sql; SUBCASE = PS.SUBCASE
CATS = ["STI", "SH", "MH", "Other"]
SOURCES = ["gmb_call", "gmb_web", "gmb_wa", "gpaid_call", "gpaid_web", "practo", "meta", "organic", "untagged"]
W = PS.W; CFG = W.CFG

# ---- exophone GMB / Google number sets (source attribution, same as patch_done_by_source) ----
wb = openpyxl.load_workbook(os.path.expanduser("~/Downloads/exophone_categorisation.xlsx"), read_only=True)
_ws = wb["All Numbers"]; _xr = list(_ws.iter_rows(values_only=True)); _xh = {c: i for i, c in enumerate(_xr[0])}
GMB_NUMS, GOOG_NUMS = set(), set()
for r in _xr[1:]:
    num = str(r[_xh["Exotel Number"]] or "").strip()[-10:]
    if not num: continue
    cat = (r[_xh["Category"]] or "").strip().lower()
    if cat == "gmb": GMB_NUMS.add(num)
    elif cat == "google": GOOG_NUMS.add(num)
GMB_IN = "','".join(sorted(GMB_NUMS)); GOOG_IN = "','".join(sorted(GOOG_NUMS))

SRC_CASE = """CASE
    WHEN gc.ph IS NOT NULL THEN 'gmb_call'
    WHEN u.us='gmb' AND u.um='whatsapp' THEN 'gmb_wa'
    WHEN u.us='gmb' THEN 'gmb_web'
    WHEN pc.ph IS NOT NULL THEN 'gpaid_call'
    WHEN u.g=1 OR u.us='google' THEN 'gpaid_web'
    WHEN u.us='practo' THEN 'practo'
    WHEN u.f=1 OR u.us IN ('fb','facebook','instagram','ig') THEN 'meta'
    WHEN u.us='organic' THEN 'organic'
    ELSE 'untagged' END"""

def sql(city, loc):
    return """WITH loc AS (SELECT id FROM allo_health.locations WHERE deleted_at IS NULL AND city='{city}' AND locality='{loc}'),
  etag AS (SELECT e.appointment_id ap_id,
      MAX(CASE WHEN et.tag_type='sti' THEN 1 ELSE 0 END) t_sti,
      MAX(CASE WHEN et.tag_type='ed_plus_pe_plus' THEN 1 ELSE 0 END) t_edpe,
      MAX(CASE WHEN et.tag_type='ed_plus' THEN 1 ELSE 0 END) t_ed,
      MAX(CASE WHEN et.tag_type='pe_plus' THEN 1 ELSE 0 END) t_pe,
      MAX(CASE WHEN et.tag_type='nssd' THEN 1 ELSE 0 END) t_nssd,
      MAX(CASE WHEN et.tag_type='others' THEN 1 ELSE 0 END) t_oth
    FROM allo_encounters.encounters e
    LEFT JOIN allo_analytics.encounter_tags et ON et.encounter_id=e.id AND et.tag_category='diagnosis' AND et.deleted_at IS NULL
    WHERE e.deleted_at IS NULL GROUP BY 1),
  diag AS (SELECT e.appointment_id ap_id,
      MAX(CASE WHEN d.description ILIKE '%porn%' OR d.description ILIKE '%masturbat%' OR d.description ILIKE '%sex%addict%' OR d.description ILIKE '%compulsive sexual%' THEN 1 ELSE 0 END) d_porn,
      MAX(CASE WHEN d.description ILIKE '%performance anxiety%' OR d.description ILIKE '%sexual%anxiety%' THEN 1 ELSE 0 END) d_pfx,
      MAX(CASE WHEN d.description ILIKE '%low sexual desire%' OR d.description ILIKE '%low desire%' OR d.description ILIKE '%low libido%' OR d.description ILIKE '%hypoactive%' THEN 1 ELSE 0 END) d_lowdes,
      MAX(CASE WHEN d.description ILIKE '%vaginismus%' OR d.description ILIKE '%dyspareunia%' OR d.description ILIKE '%anorgasmia%' OR d.description ILIKE '%arousal disorder%' OR d.description ILIKE '%fsad%' OR d.description ILIKE '%pain during sex%' OR d.description ILIKE '%female sexual%' THEN 1 ELSE 0 END) d_femsex,
      MAX(CASE WHEN d.description ILIKE '%balanitis%' OR d.description ILIKE '%phimosis%' OR d.description ILIKE '%balanoposthitis%' THEN 1 ELSE 0 END) d_foreskin,
      MAX(CASE WHEN d.description ILIKE '%delayed ejaculation%' THEN 1 ELSE 0 END) d_dejac,
      MAX(CASE WHEN d.description ILIKE '%?sti%' OR d.description ILIKE '%fear of sti%' OR d.description ILIKE '%sti scare%' OR d.description ILIKE '%sti concern%' THEN 1 ELSE 0 END) d_stic,
      MAX(CASE WHEN (d.description ILIKE '%no symptomatic sexual%' OR d.description ILIKE '%no sexual disorder%' OR d.description ILIKE '%no sexual dysfunction%' OR d.description ILIKE '%nssd%') THEN 1 ELSE 0 END) d_nodis,
      MAX(CASE WHEN d.description ILIKE '%depress%' THEN 1 ELSE 0 END) d_dep,
      MAX(CASE WHEN d.description ILIKE '%adhd%' THEN 1 ELSE 0 END) d_adhd,
      MAX(CASE WHEN d.description ILIKE '%obsessive%' OR d.description ILIKE '%ocd%' THEN 1 ELSE 0 END) d_ocd,
      MAX(CASE WHEN d.description ILIKE '%bipolar%' THEN 1 ELSE 0 END) d_bip,
      MAX(CASE WHEN d.description ILIKE '%ptsd%' OR d.description ILIKE '%grief%' THEN 1 ELSE 0 END) d_ptsd,
      MAX(CASE WHEN d.description ILIKE '%adjustment%' THEN 1 ELSE 0 END) d_adj,
      MAX(CASE WHEN d.description ILIKE '%alcohol%' OR d.description ILIKE '%nicotine%' OR d.description LIKE '%(6C4%' THEN 1 ELSE 0 END) d_sub,
      MAX(CASE WHEN d.description ILIKE '%psychosis%' OR d.description ILIKE '%schizophren%' OR d.description ILIKE '%delusional%' THEN 1 ELSE 0 END) d_psych,
      MAX(CASE WHEN d.description ILIKE '%anxiety%' OR d.description ILIKE '%panic%' OR d.description ILIKE '%agoraphobia%' THEN 1 ELSE 0 END) d_anx,
      MAX(CASE WHEN d.description LIKE '%(6A%' OR d.description LIKE '%(6B%' OR d.description LIKE '%(6C%' OR d.description LIKE '%(6D%' OR d.description LIKE '%(6E%' OR d.description ILIKE '%personality%' OR d.description ILIKE '%somatoform%' THEN 1 ELSE 0 END) d_mh
    FROM allo_encounters.encounters e JOIN allo_observations.diagnoses d ON d.encounter_id=e.id AND d.deleted_at IS NULL
    WHERE e.deleted_at IS NULL GROUP BY 1),
  ap0 AS (SELECT a.id, a.patient_id, RIGHT(p.phone_no,10) ph,
      TO_CHAR(DATE_TRUNC('week', a.created_at + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk, a.status
    FROM allo_consultations.appointments a JOIN allo_consultations.types typ ON typ.id=a.type_id AND typ.name='Screening Call'
    JOIN loc ON loc.id=a.location_id JOIN allo_persons.patient p ON p.id=a.patient_id
    WHERE a.created_at >= '{lo}' AND a.deleted_at IS NULL),
  ap AS (SELECT id, patient_id, ph, wk, status FROM (SELECT ap0.*, ROW_NUMBER() OVER (PARTITION BY patient_id, wk
      ORDER BY (CASE WHEN status='COMPLETED' THEN 0 ELSE 1 END), id) rn FROM ap0) z WHERE rn=1),
  inv AS (SELECT e.appointment_id ap_id, SUM(i.amount) amt FROM allo_encounters.encounters e
    JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.deleted_at IS NULL AND i.status='paid' WHERE e.deleted_at IS NULL GROUP BY 1),
  gc AS (SELECT DISTINCT RIGHT("from",10) ph FROM allo_vendors.exotel_calls
        WHERE RIGHT(exotel_number,10) IN ('{gmb}') AND routed_to='lead_to_call' AND direction='inbound' AND start_time>='2025-06-23'),
  pc AS (SELECT DISTINCT RIGHT("from",10) ph FROM allo_vendors.exotel_calls
        WHERE RIGHT(exotel_number,10) IN ('{goog}') AND routed_to='lead_to_call' AND direction='inbound' AND start_time>='2025-06-23'),
  u AS (SELECT ph,us,um,g,f FROM (
     SELECT RIGHT(phone_no,10) ph, LOWER(COALESCE(utm_source,'')) us, LOWER(COALESCE(utm_medium,'')) um,
       CASE WHEN gclid<>'' THEN 1 ELSE 0 END g, CASE WHEN fbclid<>'' THEN 1 ELSE 0 END f,
       ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY created_at DESC) rn
     FROM allo_persons.lead WHERE created_at>='2025-06-23' AND (utm_source IS NOT NULL OR gclid<>'' OR fbclid<>'')) z WHERE rn=1)
  SELECT ap.patient_id, ap.wk, ap.status, {subcase} subcat, {srccase} src,
    CASE WHEN inv.ap_id IS NOT NULL THEN 1 ELSE 0 END has_paid,
    CASE WHEN ap.status='COMPLETED' THEN COALESCE(inv.amt,0) ELSE 0 END rev_paise
  FROM ap LEFT JOIN etag et ON et.ap_id=ap.id LEFT JOIN diag dg ON dg.ap_id=ap.id LEFT JOIN inv ON inv.ap_id=ap.id
    LEFT JOIN gc ON gc.ph=ap.ph LEFT JOIN pc ON pc.ph=ap.ph LEFT JOIN u ON u.ph=ap.ph
  ORDER BY ap.patient_id, ap.wk;""".format(city=city.replace("'", "''"), loc=loc.replace("'", "''"),
        lo=LO, subcase=SUBCASE, srccase=SRC_CASE, gmb=GMB_IN, goog=GOOG_IN)

FIELDS = ("done", "purchased", "rev")

def compute(cfg):
    """Return (demand, comp) each = dict of rebuilt arrays; comp is for validation."""
    # gather per-patient rows
    pats = {}
    for line in run_sql(sql(cfg["city"], cfg["loc"])):
        c = line.split("\t")
        if len(c) < 7 or c[1] not in idx: continue
        pid, wk, status, subcat, src, has_paid, rev_p = c[0], c[1], c[2], c[3], c[4], c[5], c[6]
        cat = subcat.split("::")[0]
        if cat not in CATS: cat = "Other"
        if src not in SOURCES: src = "untagged"
        try: rev = round(int(float(rev_p)) / 100.0)
        except (ValueError, TypeError): rev = 0
        try: hp = int(float(has_paid))
        except (ValueError, TypeError): hp = 0
        pats.setdefault(pid, []).append({"wk": wk, "done": status == "COMPLETED",
            "cat": cat, "sub": subcat, "src": src, "purchased": hp if status == "COMPLETED" else 0, "rev": rev})

    def emptybuild():
        return {"done": {"tot": Z(), "cat": {c: Z() for c in CATS}, "sub": {}, "src": {s: Z() for s in SOURCES},
                         "cat_src": {}},
                "purchased": {"tot": Z(), "cat": {c: Z() for c in CATS}, "sub": {}},
                "rev": {"tot": Z(), "cat": {c: Z() for c in CATS}, "sub": {}}}
    demand, comp = emptybuild(), emptybuild()

    def credit(B, wk, r):
        i = idx[wk]
        for f in FIELDS:
            v = 1 if (f == "done") else r[f]
            B[f]["tot"][i] += v
            B[f]["cat"][r["cat"]][i] += v
            B[f]["sub"].setdefault(r["sub"], Z()); B[f]["sub"][r["sub"]][i] += v
        # source-split (done only, matching existing done_by_source / done_cat_source)
        B["done"]["src"][r["src"]][i] += 1
        B["done"]["cat_src"].setdefault(r["cat"], {}).setdefault(r["src"], Z())[i] += 1

    for pid, rows in pats.items():
        rows.sort(key=lambda x: x["wk"])
        book_weeks = [x["wk"] for x in rows]                    # every booking week (may repeat-free already: dedup per week)
        comps = [x for x in rows if x["done"]]
        used = [False] * len(book_weeks)
        for r in comps:
            credit(comp, r["wk"], r)                            # completion-week (validation)
            # earliest un-credited booking week <= completion week
            j = next((k for k, bw in enumerate(book_weeks) if (not used[k]) and bw <= r["wk"]), None)
            if j is None:  # fallback: earliest un-credited at all
                j = next((k for k, bw in enumerate(book_weeks) if not used[k]), None)
            dw = book_weeks[j] if j is not None else r["wk"]
            if j is not None: used[j] = True
            credit(demand, dw, r)                               # demand-week
    return demand, comp

def totals(B):
    return (sum(B["done"]["tot"]), sum(B["purchased"]["tot"]), sum(B["rev"]["tot"]))

if __name__ == "__main__":
    d = json.load(open(OUT)); items = list(d["clinics"].items())
    ok = 0; skipped = []; done_n = 0
    for slug, c in items:
        if c.get("bottom", {}).get("demand_first"): ok += 1; continue
        cfg = CFG.get(slug)
        if not cfg: continue
        try:
            demand, comp = compute(cfg)
        except BaseException as e:
            print("[FAIL query] %s: %s" % (cfg.get("disp", slug), e), flush=True); continue
        # validate: completion-week recompute must reproduce existing totals
        ex_d = sum(c["bottom"]["done"]); ex_p = sum(c["bottom"]["purchased"]); ex_r = sum(c["bottom"]["rev"])
        cd, cp, cr = totals(comp)
        def near(a, b, tol=0.03, floor=3):
            return abs(a - b) <= max(floor, tol * max(a, b, 1))
        if not (near(cd, ex_d) and near(cp, ex_p) and near(cr, ex_r, 0.05, 500)):
            skipped.append((cfg["disp"], "recompute %d/%d/%d vs existing %d/%d/%d" % (cd, cp, cr, ex_d, ex_p, ex_r)))
            continue
        # write demand-first (BOOKED untouched; only done/purchased/rev move)
        b = c["bottom"]
        b["done"] = demand["done"]["tot"]; b["purchased"] = demand["purchased"]["tot"]; b["rev"] = demand["rev"]["tot"]
        for cat in CATS:
            b.setdefault("by_cat", {}).setdefault(cat, {})
            b["by_cat"][cat]["done"] = demand["done"]["cat"][cat]
            b["by_cat"][cat]["purchased"] = demand["purchased"]["cat"][cat]
            b["by_cat"][cat]["rev"] = demand["rev"]["cat"][cat]
        for sub, arr in demand["done"]["sub"].items():
            if sub in b.get("by_subcat", {}):
                b["by_subcat"][sub]["done"] = arr
                b["by_subcat"][sub]["purchased"] = demand["purchased"]["sub"].get(sub, Z())
                b["by_subcat"][sub]["rev"] = demand["rev"]["sub"].get(sub, Z())
        c["done_by_source"] = demand["done"]["src"]
        c["done_cat_source"] = {cat: {s: arr for s, arr in srcs.items() if any(arr)}
                                for cat, srcs in demand["done"]["cat_src"].items() if any(any(a) for a in srcs.values())}
        b["demand_first"] = True
        ok += 1; done_n += 1
        moved = sum(comp["done"]["tot"]) - sum(demand["done"]["tot"][idx[cfg["city"]]] if False else [0])  # noop
        print("[ok %d] %s  done=%d (shift-safe)" % (done_n, cfg["disp"], sum(demand["done"]["tot"])), flush=True)
        if done_n % 6 == 0: json.dump(d, open(OUT, "w"), separators=(",", ":"))
    json.dump(d, open(OUT, "w"), separators=(",", ":"))
    print("\npatched %d clinics (demand-first); %d skipped (drift)" % (done_n, len(skipped)))
    for nm, why in skipped[:20]: print("  SKIP", nm, "|", why)
