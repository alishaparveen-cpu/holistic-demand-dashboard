#!/usr/bin/env python3
"""Build data_slots_sc.json — SLOT-LEVEL (appointment-level) SC-OFFLINE funnel per clinic/doctor/week.
Mirrors the org's canonical slot query: total_slots · completed · no_show · cancelled · reschedule (by doctor / by patient).
Slot-level B2D = completed / total_slots. Reschedule split via the shrinkage flag (in a shrunk block = by doctor, else by patient).
Keyed 'city|locality' (doctor's block clinic) + by_doctor. Run: AWS_PROFILE=redshift-data python3 scripts/build_slots.py
"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
TELE = "'c7d8c9d2-f389-4e8f-a260-71110195b83f','ffe8d849-3099-48fe-a2df-e324c4befe56'"

SQL = f"""
WITH current_range AS (SELECT DATE_TRUNC('month', DATEADD(month,-3,GETDATE())) + INTERVAL '5.5 hours' AS start_range),
numbers AS (SELECT ROW_NUMBER() OVER () - 1 AS num FROM (SELECT NULL FROM allo_consultations.appointment_blocks LIMIT 150) t1),
expanded_dates AS (SELECT CURRENT_DATE - 1 - num AS dt FROM numbers),
doctor_sessions AS (
  SELECT DATE(b.start_time + INTERVAL '5 HOURS 30 MINUTES') AS dt, b.provider_id,
    (b.start_time + INTERVAL '5 HOURS 30 MINUTES') AS start_time, (b.end_time + INTERVAL '5 HOURS 30 MINUTES') AS end_time
  FROM allo_consultations.appointment_blocks b
  LEFT JOIN allo_consultations.appointment_block_type_maps ab ON b.id=ab.appointment_block_id
  WHERE b.is_bookable=1 AND b.deleted_at IS NULL AND ab.offline_location_id IS NOT NULL AND ab.deleted_at IS NULL),
shrinkage_blocks_expanded AS (
  SELECT DISTINCT ed.dt AS shrink_dt, sb.provider_id, GREATEST(sb.shrink_start, ed.dt) AS shrink_start,
    CASE WHEN sb.shrink_end::TIME = TIME '00:00:00' THEN sb.shrink_end::DATE - 1 + TIME '23:59:59' ELSE sb.shrink_end END AS shrink_end
  FROM (SELECT b.provider_id, b.start_time + INTERVAL '5 HOURS 30 MINUTES' AS shrink_start, b.end_time + INTERVAL '5 HOURS 30 MINUTES' AS shrink_end
        FROM allo_consultations.appointment_blocks b WHERE b.is_bookable=0 AND b.deleted_at IS NULL) sb
  JOIN expanded_dates ed ON ed.dt BETWEEN sb.shrink_start::DATE AND sb.shrink_end::DATE),
valid_shrinkage AS (
  SELECT DISTINCT sb.shrink_dt AS dt, sb.provider_id,
    GREATEST(sb.shrink_start, dws.start_time) AS shrink_start_time, LEAST(sb.shrink_end, dws.end_time) AS shrink_end_time
  FROM shrinkage_blocks_expanded sb JOIN doctor_sessions dws
    ON sb.provider_id=dws.provider_id AND sb.shrink_dt=dws.dt AND sb.shrink_start<dws.end_time AND sb.shrink_end>dws.start_time
  WHERE GREATEST(sb.shrink_start, dws.start_time) < LEAST(sb.shrink_end, dws.end_time)),
appt_shrinkage_flag AS (
  SELECT DISTINCT app.id AS appt_id, 1 AS in_shrinkage_flag
  FROM allo_consultations.appointments app JOIN valid_shrinkage vs
    ON vs.provider_id=app.provider_id AND vs.dt=DATE(app.start_time + INTERVAL '5.5 hours')
    AND (app.start_time + INTERVAL '5.5 hours') >= vs.shrink_start_time AND (app.start_time + INTERVAL '5.5 hours') < vs.shrink_end_time
  WHERE app.deleted_at IS NULL),
doctor_location AS (
  SELECT DISTINCT DATE(ab.start_time + INTERVAL '5.5 hours') AS block_dt, ab.id AS block_id, ab.provider_id, loc.city, loc.locality
  FROM allo_consultations.appointment_block_type_maps abtm
  LEFT JOIN allo_consultations.appointment_blocks ab ON abtm.appointment_block_id=ab.id
  LEFT JOIN allo_health.locations loc ON abtm.offline_location_id=loc.id AND loc.deleted_at IS NULL
  WHERE abtm.deleted_at IS NULL AND ab.deleted_at IS NULL AND abtm.offline_location_id IS NOT NULL),
base AS (
  SELECT app.id AS appt_id,
    date_trunc('week', app.start_time + INTERVAL '5.5 hours')::date AS week_start,
    COALESCE(dl.city,'Online') AS doc_city, COALESCE(dl.locality,'Online') AS doc_locality, pro.name AS doctor,
    CASE WHEN app.location_id IN ({TELE}) THEN 0 ELSE 1 END AS offline_flag,
    COALESCE(sf.in_shrinkage_flag,0) AS in_shrinkage_flag,
    CASE WHEN app.status IN ('SCHEDULED','PATIENT_JOINED','IN_PROGRESS','PROVIDER_JOINED') THEN 'SCHEDULED'
         WHEN LOWER(app.status)='cancelled' THEN 'CANCELLED'
         WHEN app.status IN ('RECONSULTED','COMPLETED') THEN 'COMPLETED'
         WHEN app.updated_at > app.start_time THEN 'No Show'
         WHEN app.updated_at <= app.start_time THEN 'Reschedule' ELSE 'Others' END AS final_status
  FROM allo_consultations.appointments app
  JOIN allo_persons.providers pro ON app.provider_id=pro.id AND pro.deleted_at IS NULL
  JOIN allo_consultations.types typ ON app.type_id=typ.id AND typ.deleted_at IS NULL AND typ.name='Screening Call'
  LEFT JOIN doctor_location dl ON app.provider_id=dl.provider_id AND DATE(app.start_time + INTERVAL '5.5 hours')=dl.block_dt AND app.block_id=dl.block_id
  LEFT JOIN appt_shrinkage_flag sf ON sf.appt_id=app.id
  JOIN current_range cr ON TRUE
  WHERE app.deleted_at IS NULL AND app.start_time + INTERVAL '5.5 hours' >= cr.start_range)
SELECT doc_city, doc_locality, doctor, week_start,
  COUNT(*) AS total_slots,
  SUM(CASE WHEN final_status='COMPLETED' THEN 1 ELSE 0 END) AS completed,
  SUM(CASE WHEN final_status='No Show' THEN 1 ELSE 0 END) AS no_show,
  SUM(CASE WHEN final_status='CANCELLED' THEN 1 ELSE 0 END) AS cancelled,
  SUM(CASE WHEN final_status='Reschedule' AND in_shrinkage_flag=1 THEN 1 ELSE 0 END) AS resched_doc,
  SUM(CASE WHEN final_status='Reschedule' AND in_shrinkage_flag=0 THEN 1 ELSE 0 END) AS resched_pat
FROM base WHERE offline_flag=1
GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;
"""

FIELDS = ["total_slots", "completed", "no_show", "cancelled", "resched_doc", "resched_pat"]


def run(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("query failed:\n" + (p.stderr or "")[:800] + "\n"); sys.exit(1)
    return [ln.split("\t") for ln in p.stdout.strip().splitlines() if ln.strip()]


def main():
    rows = run(SQL)
    weeks = sorted({r[3] for r in rows})
    widx = {w: i for i, w in enumerate(weeks)}
    NW = len(weeks)
    blank = lambda: {f: [0]*NW for f in FIELDS}
    clinics = {}
    for r in rows:
        city, loc, doctor, wk = r[0], r[1], r[2], r[3]
        key = city + "|" + loc
        i = widx[wk]
        vals = [int(float(x)) for x in r[4:10]]
        o = clinics.setdefault(key, blank())
        dd = o.setdefault("by_doctor", {}).setdefault(doctor, blank())
        for f, v in zip(FIELDS, vals):
            o[f][i] += v; dd[f][i] += v
    out = {"_meta": {"weeks": weeks, "source": "allo_consultations.appointments · SC OFFLINE slot-level (canonical status logic) · doctor's block clinic",
                     "note": "Slot-level B2D = completed/total_slots. reschedule split by shrinkage (doctor vs patient). Keyed city|locality + by_doctor.",
                     "fields": FIELDS},
           "clinics": clinics}
    json.dump(out, open(os.path.join(ROOT, "data_slots_sc.json"), "w"), separators=(",", ":"))
    tot = sum(sum(o["total_slots"]) for o in clinics.values()); comp = sum(sum(o["completed"]) for o in clinics.values())
    print(f"data_slots_sc.json · {len(clinics)} clinic-keys · {NW} weeks ({weeks[0]}→{weeks[-1]}) · total_slots {tot} · completed {comp} · slot-B2D {round(100*comp/max(1,tot))}%")


if __name__ == "__main__":
    main()
