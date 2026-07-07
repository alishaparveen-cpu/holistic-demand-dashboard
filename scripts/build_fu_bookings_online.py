#!/usr/bin/env python3
"""Build data_fu_bookings_online.json — FOLLOW-UP ONLINE (telehealth), mirror of the offline FU cube.

Follow Up appointments with location_id IN (telehealth UUIDs) OR NULL. Single national bucket 'Online|Online',
booked/done (distinct patient per week) + by_doctor. Run: AWS_PROFILE=redshift-data python3 scripts/build_fu_bookings_online.py
"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
START_WK = "2025-07-01"
TELE = "'c7d8c9d2-f389-4e8f-a260-71110195b83f','ffe8d849-3099-48fe-a2df-e324c4befe56'"

SQL = f"""
WITH doctor_location AS (
  SELECT DISTINCT DATE(ab.start_time + INTERVAL '5.5 hours') AS block_dt, ab.id AS block_id, ab.provider_id, loc.city, loc.locality
  FROM allo_consultations.appointment_block_type_maps abtm
  LEFT JOIN allo_consultations.appointment_blocks ab ON abtm.appointment_block_id=ab.id
  LEFT JOIN allo_health.locations loc ON abtm.offline_location_id=loc.id AND loc.deleted_at IS NULL
  WHERE abtm.deleted_at IS NULL AND ab.deleted_at IS NULL AND abtm.offline_location_id IS NOT NULL
),
fu AS (
  SELECT apt.patient_id, apt.status,
    date_trunc('week', apt.start_time + interval '5.5 hours')::date AS week_start,
    COALESCE(pro.name,'—') AS doctor,
    COALESCE(dl.city,'Online') AS city, COALESCE(dl.locality,'Online') AS locality
  FROM allo_consultations.appointments apt
  JOIN allo_consultations.types t ON apt.type_id=t.id AND t.deleted_at IS NULL AND t.name='Follow Up'
  JOIN allo_health.locations loc ON apt.location_id=loc.id AND loc.deleted_at IS NULL AND lower(loc.name) LIKE '%online%'
  LEFT JOIN allo_persons.providers pro ON apt.provider_id=pro.id AND pro.deleted_at IS NULL
  LEFT JOIN doctor_location dl ON apt.provider_id=dl.provider_id AND DATE(apt.start_time+INTERVAL '5.5 hours')=dl.block_dt AND apt.block_id=dl.block_id
  WHERE apt.deleted_at IS NULL
)
SELECT city, locality, doctor, week_start,
  count(distinct patient_id) AS booked,
  count(distinct case when status IN ('COMPLETED','RECONSULTED') then patient_id end) AS done
FROM fu WHERE week_start >= '{START_WK}' GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;
"""


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
    FIELDS = ["booked", "done"]
    blank = lambda: {f: [0]*NW for f in FIELDS}
    clinics = {}
    for r in rows:
        city, loc, doctor, wk = r[0], r[1], r[2], r[3]
        key = city + "|" + loc
        i = widx[wk]
        vals = [int(v) for v in r[4:6]]
        o = clinics.setdefault(key, blank())
        dd = o.setdefault("by_doctor", {}).setdefault(doctor, blank())
        for f, v in zip(FIELDS, vals):
            o[f][i] += v; dd[f][i] += v
    out = {"_meta": {"weeks": weeks, "source": "allo_consultations.appointments · Follow Up ONLINE (telehealth) attributed to the doctor's block clinic that day · service week · distinct patient",
                     "note": "Per-clinic online (city|locality); unresolved → 'Online|Online'. by_doctor depth.", "fields": FIELDS},
           "clinics": clinics}
    json.dump(out, open(os.path.join(ROOT, "data_fu_bookings_online.json"), "w"), separators=(",", ":"))
    tot = sum(sum(o["booked"]) for o in clinics.values())
    nat = sum(clinics.get("Online|Online", blank())["booked"])
    print(f"data_fu_bookings_online.json · {len(clinics)} clinic-keys · {NW} weeks ({weeks[0]}→{weeks[-1]}) · total booked {tot} · unresolved {nat} ({100*nat//max(1,tot)}%)")


if __name__ == "__main__":
    main()
