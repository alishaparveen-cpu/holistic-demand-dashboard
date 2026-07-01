#!/usr/bin/env python3
"""Break each week's SC bookings into COHORTS (does NOT change booking totals or done).

Total SC bookings/week stay exactly as-is; we just label each deduped (patient, week, clinic)
booking so the rebook inflation becomes visible:
  new_fresh  = patient's first-ever SC, their lead arrived the same week
  new_old    = patient's first-ever SC, lead arrived an earlier week (lag)
  rebook     = patient booked an SC before but NEVER completed (no-show / reschedule churn)
  relapse    = patient COMPLETED a prior SC and is booking again (returning demand)
Also carries done within each cohort (eventual completion of that booking) for a cohort done%.

Writes clinic['book_cohort'] = {cohort: {booked:[52], done:[52]}}. Validates the cohort booked
sum reconciles to the existing bottom.booked per clinic (only labels, totals preserved).
Resumable via clinic['book_cohort']. Run: AWS_PROFILE=redshift-data python3 scripts/patch_book_cohort.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import patch_subcat as PS
ROOT = PS.ROOT; OUT = os.path.join(ROOT, "data_source_recon.json")
idx = PS.idx; Z = PS.Z; LO = PS.LO; run_sql = PS.run_sql
COHORTS = ["new_fresh", "new_old", "rebook", "relapse"]

SQL = """WITH sc AS (
  SELECT a.id, a.patient_id, RIGHT(p.phone_no,10) ph, loc.city ct, loc.locality lc, a.created_at, a.status,
    TO_CHAR(DATE_TRUNC('week', a.created_at + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.deleted_at IS NULL AND loc.locality IS NOT NULL AND loc.locality<>''
  JOIN allo_persons.patient p ON p.id=a.patient_id
  WHERE a.deleted_at IS NULL AND a.created_at >= '2023-01-01' AND a.created_at < '2026-06-29'),
 seqd AS (
  SELECT sc.*,
    ROW_NUMBER() OVER (PARTITION BY patient_id ORDER BY created_at, id) seq,
    MAX(CASE WHEN status='COMPLETED' THEN created_at END)
      OVER (PARTITION BY patient_id ORDER BY created_at, id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) prior_comp,
    MAX(CASE WHEN status='COMPLETED' THEN 1 ELSE 0 END)
      OVER (PARTITION BY patient_id, ct, lc) ever_done_here
  FROM sc),
 dd AS (   -- one row per patient/week/clinic, COMPLETED-preferred (matches existing booking dedup)
  SELECT *, ROW_NUMBER() OVER (PARTITION BY patient_id, ct, lc, wk
     ORDER BY (CASE WHEN status='COMPLETED' THEN 0 ELSE 1 END), id) rn FROM seqd),
 ld AS (   -- patient's earliest lead week (main_source_wise_leads)
  SELECT phone_no1 ph, MIN(DATE_TRUNC('week', created_on_date + INTERVAL '5 hours 30 minutes')) lwk
  FROM production.public.main_source_wise_leads WHERE created_on_date >= '2023-01-01' GROUP BY 1)
SELECT dd.ct, dd.lc, dd.wk,
  CASE WHEN dd.seq=1 AND (ld.lwk IS NULL OR ld.lwk >= DATE_TRUNC('week', dd.created_at + INTERVAL '5 hours 30 minutes')) THEN 'new_fresh'
       WHEN dd.seq=1 THEN 'new_old'
       WHEN dd.prior_comp IS NOT NULL THEN 'relapse'
       ELSE 'rebook' END cohort,
  COUNT(*) booked,
  SUM(CASE WHEN dd.ever_done_here=1 THEN 1 ELSE 0 END) done_ever,
  SUM(CASE WHEN dd.status='COMPLETED' THEN 1 ELSE 0 END) done_wk
FROM dd LEFT JOIN ld ON ld.ph=dd.ph
WHERE dd.rn=1 AND dd.wk >= '{lo}'
GROUP BY 1,2,3,4;""".format(lo=LO)

def slugify(loc, city):
    s = lambda x: "".join(ch if ch.isalnum() else "_" for ch in (x or "").strip().lower())
    return s(loc) + "_" + s(city)
CITY_ALIAS = {"bengaluru": "bangalore", "gurgaon": "gurugram"}
def norm_city(c): c = (c or "").strip().lower(); return CITY_ALIAS.get(c, c)

if __name__ == "__main__":
    d = json.load(open(OUT)); clinics = d["clinics"]
    agg = {}   # slug -> cohort -> {booked,done_ever,done_wk}
    for row in run_sql(SQL):
        r = row.split("\t") if isinstance(row, str) else row
        if len(r) < 7: continue
        ct, lc, wk, coh, bk, de, dw = r[:7]
        if wk not in idx or coh not in COHORTS: continue
        slug = slugify(lc, norm_city(ct)); i = idx[wk]
        try: bk = int(float(bk)); de = int(float(de)); dw = int(float(dw))
        except ValueError: continue
        a = agg.setdefault(slug, {c: {"booked": Z(), "done_ever": Z(), "done_wk": Z()} for c in COHORTS})
        a[coh]["booked"][i] += bk; a[coh]["done_ever"][i] += de; a[coh]["done_wk"][i] += dw

    matched = 0; drift = []
    for slug, c in clinics.items():
        if slug not in agg: continue
        coh = agg[slug]
        # validate: cohort booked total ~ existing bottom.booked
        cb = sum(sum(coh[k]["booked"]) for k in COHORTS)
        eb = sum(c.get("bottom", {}).get("booked", []))
        if eb and abs(cb - eb) > max(5, 0.06 * eb):
            drift.append((slug, cb, eb)); continue
        c["book_cohort"] = coh; matched += 1
    json.dump(d, open(OUT, "w"), separators=(",", ":"))
    # network cohort mix
    tot = {k: sum(sum(agg[s][k]["booked"]) for s in agg) for k in COHORTS}
    T = sum(tot.values()) or 1
    print("patched %d clinics | drift-skipped %d" % (matched, len(drift)))
    print("network booking mix:", {k: "%d (%.0f%%)" % (v, 100 * v / T) for k, v in tot.items()})
    for s, cb, eb in drift[:10]: print("  DRIFT", s, "cohort=%d existing=%d" % (cb, eb))
