#!/usr/bin/env python3
"""Build data_fu_bookings.json — FOLLOW-UP booking→done, per clinic × week (ops view, sibling of SC demand).

Follow-Up appointments (type='Follow Up'), offline (loc.name NOT LIKE '%online%'), keyed on service week
(DATE_TRUNC('week', start_time + 5.5h)). Distinct patient per (clinic, week) — additive, same grain as SC.
FU has no first-time/lead/new-repeat split (all FU patients are returning) — just booked + done for B2D.

Per clinic ("City|Locality") × week: booked (distinct patient), done (distinct patient COMPLETED/RECONSULTED),
with a by_doctor marginal. Run: AWS_PROFILE=redshift-data python3 scripts/build_fu_bookings.py
"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
START_WK = "2025-07-01"
TELE = "'c7d8c9d2-f389-4e8f-a260-71110195b83f','ffe8d849-3099-48fe-a2df-e324c4befe56'"   # 2 telehealth UUIDs = ONLINE; OFFLINE = everything else (mirror the online cube; matches sheet offline_flag)

SQL = f"""
WITH fu AS (
  SELECT apt.patient_id, apt.status,
    date_trunc('week', apt.start_time + interval '5.5 hours')::date AS week_start,
    loc.city, loc.locality AS clinic, COALESCE(pro.name,'—') AS doctor,
    EXTRACT(dow FROM apt.start_time + interval '5.5 hours') AS dow,   -- 0=Sun … 6=Sat, IST
    -- one representative appt per patient per (clinic, doctor, week) so the weekday/weekend
    -- split sums back to booked (each distinct patient bucketed once, by their first appt's day)
    row_number() over (partition by apt.patient_id,
      date_trunc('week', apt.start_time + interval '5.5 hours'), loc.city, loc.locality, COALESCE(pro.name,'—')
      order by apt.start_time asc) AS rn
  FROM allo_consultations.appointments apt
  JOIN allo_consultations.types t ON apt.type_id=t.id AND t.deleted_at IS NULL AND t.name='Follow Up'
  JOIN allo_health.locations loc ON apt.location_id=loc.id AND loc.deleted_at IS NULL AND apt.location_id NOT IN ({TELE})   -- OFFLINE = not the 2 telehealth UUIDs (mirror online cube; was loc.name NOT LIKE)
  LEFT JOIN allo_persons.providers pro ON apt.provider_id=pro.id AND pro.deleted_at IS NULL
  WHERE apt.deleted_at IS NULL
)
SELECT city, clinic, doctor, week_start,
  count(distinct patient_id) AS booked,
  count(distinct case when status IN ('COMPLETED','RECONSULTED') then patient_id end) AS done,
  count(distinct case when rn=1 and dow NOT IN (0,6) then patient_id end) AS bkwd,   -- weekday bookings
  count(distinct case when rn=1 and dow IN (0,6) then patient_id end) AS bkwe,       -- weekend bookings
  count(distinct case when status IN ('COMPLETED','RECONSULTED') and dow NOT IN (0,6) then patient_id end) AS done_wkday,   -- weekday DONE
  count(distinct case when status IN ('COMPLETED','RECONSULTED') and dow IN (0,6) then patient_id end) AS done_wkend        -- weekend DONE
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
    FIELDS = ["booked", "done", "bkwd", "bkwe", "done_wkday", "done_wkend"]

    def blank():
        return {f: [0]*NW for f in FIELDS}

    clinics = {}
    for r in rows:
        city, clinic, doctor, wk = r[0], r[1], r[2], r[3]
        key = f"{city}|{clinic}"
        i = widx[wk]
        vals = [int(v) for v in r[4:10]]
        o = clinics.setdefault(key, blank())
        dd = o.setdefault("by_doctor", {}).setdefault(doctor, blank())
        for f, v in zip(FIELDS, vals):
            o[f][i] += v
            dd[f][i] += v

    out = {"_meta": {"weeks": weeks, "source": "allo_consultations.appointments · Follow Up offline · service week · distinct patient",
                     "note": "Ops view: FU booked/done (B2D=done/booked). No lead/new-repeat split. Additive.", "fields": FIELDS},
           "clinics": clinics}
    json.dump(out, open(os.path.join(ROOT, "data_fu_bookings.json"), "w"), separators=(",", ":"))
    vwk = "2026-06-22"

    def cs(city, f):
        return sum(o[f][widx[vwk]] for k, o in clinics.items() if k.split("|")[0] == city) if vwk in widx else 0
    natB = sum(o["booked"][widx[vwk]] for o in clinics.values()) if vwk in widx else 0
    natD = sum(o["done"][widx[vwk]] for o in clinics.values()) if vwk in widx else 0
    print(f"data_fu_bookings.json · {len(clinics)} clinics · {NW} weeks ({weeks[0]}→{weeks[-1]})")
    print(f"\n── FU {vwk} ──")
    for c in ["Bangalore", "Mumbai", "Hyderabad", "Chennai", "Pune"]:
        b, d = cs(c, "booked"), cs(c, "done")
        print(f"  {c:11} FU booked {b:4}  done {d:4}  B2D {round(d/b*100) if b else 0}%")
    print(f"  NATIONAL   FU booked {natB}  done {natD}  B2D {round(natD/natB*100) if natB else 0}%")


if __name__ == "__main__":
    main()
