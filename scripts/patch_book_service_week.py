#!/usr/bin/env python3
"""Re-key OFFLINE SC bookings to the SERVICE week (appointment start_time), not the booking-CREATION
week — so the master funnel's Booking → Done is a true B2D on one time axis, matching the ops
"SC Offline B2D funnel" (of the SCs scheduled this week, how many completed).

Before: bottom.booked + book_cohort were bucketed by created_at (demand: when the booking was MADE),
while done is bucketed by the appointment/completion week — so book→done% mixed two axes.
After : booking is bucketed by DATE_TRUNC('week', start_time) with distinct patients per
(patient, city, locality, service-week) — exactly the manager's Booking(P). Done is untouched
(already service/completion week and already reconciles), so book→done% now == the manager's B2D%.

Overwrites bottom.booked = Σ cohort booked (service week) and book_cohort (service week). Prints an
Ameerpet spot-check so the reconciliation is visible. Run: AWS_PROFILE=redshift-data python3 scripts/patch_book_service_week.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import patch_subcat as PS
ROOT = PS.ROOT; OUT = os.path.join(ROOT, "data_source_recon.json")
idx = PS.idx; Z = PS.Z; LO = PS.LO; run_sql = PS.run_sql
COHORTS = ["new_fresh", "new_old", "rebook", "relapse"]

# same cohort logic as patch_book_cohort, but the OUTPUT week (wk) = SERVICE week (start_time)
SQL = """WITH sc AS (
  SELECT a.id, a.patient_id, RIGHT(p.phone_no,10) ph, loc.city ct, loc.locality lc, a.created_at, a.status,
    TO_CHAR(DATE_TRUNC('week', a.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.deleted_at IS NULL AND loc.locality IS NOT NULL AND loc.locality<>''
  JOIN allo_persons.patient p ON p.id=a.patient_id
  WHERE a.deleted_at IS NULL AND a.start_time >= '2023-01-01' AND a.start_time < '2026-06-29'),
 seqd AS (
  SELECT sc.*,
    ROW_NUMBER() OVER (PARTITION BY patient_id ORDER BY created_at, id) seq,
    MAX(CASE WHEN status='COMPLETED' THEN created_at END)
      OVER (PARTITION BY patient_id ORDER BY created_at, id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) prior_comp,
    MAX(CASE WHEN status='COMPLETED' THEN 1 ELSE 0 END)
      OVER (PARTITION BY patient_id, ct, lc) ever_done_here
  FROM sc),
 dd AS (   -- one row per patient/service-week/clinic, COMPLETED-preferred
  SELECT *, ROW_NUMBER() OVER (PARTITION BY patient_id, ct, lc, wk
     ORDER BY (CASE WHEN status='COMPLETED' THEN 0 ELSE 1 END), id) rn FROM seqd),
 ld AS (
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
    agg = {}   # slug -> cohort -> {booked,done_wk}
    for row in run_sql(SQL):
        r = row.split("\t") if isinstance(row, str) else row
        if len(r) < 7: continue
        ct, lc, wk, coh, bk, de, dw = r[:7]
        if wk not in idx or coh not in COHORTS: continue
        slug = slugify(lc, norm_city(ct)); i = idx[wk]
        try: bk = int(float(bk)); de = int(float(de)); dw = int(float(dw))
        except ValueError: continue
        a = agg.setdefault(slug, {c: {"booked": Z(), "done_ever": Z(), "done_wk": Z()} for c in COHORTS})
        a[coh]["booked"][i] += bk; a[coh]["done_wk"][i] += dw; a[coh]["done_ever"][i] += de

    matched = 0
    for slug, c in clinics.items():
        if slug not in agg: continue
        coh = agg[slug]
        c.setdefault("bottom", {})["booked"] = [sum(coh[k]["booked"][i] for k in COHORTS) for i in range(len(Z()))]
        c["book_cohort"] = coh
        c["bottom"]["booked_service_week"] = True
        matched += 1
    json.dump(d, open(OUT, "w"), separators=(",", ":"))
    print("re-keyed %d clinics to SERVICE-week booking" % matched)
    am = clinics.get("ameerpet_hyderabad", {})
    if am:
        wk = d["_meta"]["weeks"][:7]
        bk = am["bottom"]["booked"][:7]; dn = am["bottom"]["done"][:7]
        print("Ameerpet weeks :", wk)
        print("Ameerpet booked:", bk, " (manager: 34,53,69,53,52,41,39)")
        print("Ameerpet done  :", dn, " (manager: 19,28,38,25,22,20,27)")
        print("Ameerpet B2D%  :", [round(100 * dn[i] / bk[i]) if bk[i] else None for i in range(7)])
