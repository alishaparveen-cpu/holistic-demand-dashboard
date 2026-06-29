#!/usr/bin/env python3
"""City paid-call demand POOL for Bangalore → data_bangalore_pool.json.

Google paid ads run at CITY level on a single shared call-asset number (8045680561) — no clinic
is chosen at the call. So a paid CALLER who never books has no clinic and is invisible in the
clinic-level leads spine (and therefore in the city = Σ clinics total). This pool surfaces that:
  total  = distinct callers to 8045680561 (routed_to=lead_to_call, inbound), by call-week
  booked = of those, the ones who booked at ANY Bangalore clinic within [-2d, +30d] of the call
           (= the paid-call demand the city CAPTURED — already inside the leads spine as paid_call)
  lost   = total - booked  (paid-call demand the city LOST — never resolved to any clinic;
           this is exactly what is "unattributed" at the clinic level)
Backtrack by phone (RIGHT(...,10)). Run: AWS_PROFILE=redshift-data python3 scripts/pull_bangalore_pool.py
"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11",
         "2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]
idx = {w: i for i, w in enumerate(WEEKS)}; NW = len(WEEKS)
PAID_NUM = "8045680561"

SQL = """WITH calls AS (
    SELECT RIGHT(ec."from",10) ph,
           TO_CHAR(DATE_TRUNC('week', ec.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk,
           MIN(ec.start_time) ct
    FROM allo_vendors.exotel_calls ec
    WHERE RIGHT(ec.exotel_number,10)='{paid}' AND ec.routed_to='lead_to_call' AND ec.direction='inbound'
      AND ec.start_time >= '2026-03-23' AND ec.start_time < '2026-06-22'
    GROUP BY 1,2),
  bk AS (
    SELECT RIGHT(p.phone_no,10) ph, a.start_time st
    FROM allo_consultations.appointments a
    JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.city='Bangalore' AND loc.deleted_at IS NULL
    JOIN allo_persons.patient p ON p.id=a.patient_id
    WHERE a.deleted_at IS NULL AND a.start_time >= '2026-03-21')
  SELECT calls.wk,
    COUNT(DISTINCT calls.ph) total,
    COUNT(DISTINCT CASE WHEN bk.ph IS NOT NULL THEN calls.ph END) booked
  FROM calls
  LEFT JOIN bk ON bk.ph=calls.ph AND bk.st BETWEEN calls.ct - INTERVAL '2 days' AND calls.ct + INTERVAL '30 days'
  GROUP BY 1 ORDER BY 1;""".format(paid=PAID_NUM)

p = subprocess.run([sys.executable, RQ], input=SQL, capture_output=True, text=True)
if p.returncode != 0 or "ERROR" in (p.stderr or ""):
    sys.stderr.write("bangalore pool query failed: " + (p.stderr or "")[:400] + "\n"); sys.exit(1)
total=[0]*NW; booked=[0]*NW
for line in p.stdout.strip().splitlines():
    c = line.split("\t")
    if len(c) < 3 or c[0] not in idx: continue
    i = idx[c[0]]
    try: total[i]=int(c[1]); booked[i]=int(c[2])
    except ValueError: continue
lost=[total[i]-booked[i] for i in range(NW)]
out = {"_meta": {"weeks": WEEKS, "city": "Bangalore", "paid_number": PAID_NUM,
        "source": "allo_vendors.exotel_calls (shared paid # 8045680561, routed_to=lead_to_call) backtracked to Bangalore-clinic Screening Calls, -2/+30d, by call-week",
        "note": "City paid-call demand. total=distinct callers; booked=booked at ANY Bangalore clinic in window (captured — inside the leads spine as paid_call); lost=never booked anywhere (the demand that is unattributed at clinic level). CALL VOLUME, not leads. ⚠ Latest 1-2 weeks undercount booked (the +30d window is still open)."},
    "total": total, "booked": booked, "lost": lost}
json.dump(out, open(os.path.join(ROOT, "data_bangalore_pool.json"), "w"), separators=(",", ":"))
i=0
print("wrote data_bangalore_pool.json")
for i in range(6):
    conv = round(booked[i]/total[i]*100) if total[i] else 0
    print(f"  {WEEKS[i]}: total {total[i]} = booked {booked[i]} (captured) + lost {lost[i]}  · {conv}% converted")
