#!/usr/bin/env python3
"""Build data_availability.json — roster capacity per clinic × week (L2 Roster & Slots, realized).

Per "City|Locality" × service week (matches the other two matched files):
  opened_hrs   = bookable appointment-block minutes / 60
  shrink_hrs   = overlapping non-bookable block minutes / 60
  net_sc_hrs   = realized SC roster-slot minutes / 60   (capacity that actually stood)
  net_sc_slots = realized SC slots  (denominator for Utilisation = done / net_sc_slots)
  net_rpt_slots= realized follow-up slots
  active_days / wkday_days / wkend_days  (denominator for booking velocity = booked / active_days)

Offline realized SC slots: type_id cd02525c…, is_realized=1, not overlapping non-bookable, booked-or-available.
Range = last ~4 months (roster tables are heavy). Run (background): AWS_PROFILE=redshift-data python3 scripts/build_availability.py
"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
SC_TYPE = "'cd02525c-1528-4047-a12c-1ad526c28c9a'"
RPT_TYPE = "'871a9ff6-e076-4fef-9aee-14c566e67d71'"
TELE1 = "'c7d8c9d2-f389-4e8f-a260-71110195b83f'"

SQL = f"""
WITH doctor_sessions AS (
  SELECT DISTINCT DATE(b.start_time + INTERVAL '5.5 hours') AS dt, p.name AS pro_name,
    l.city, l.locality, l.name AS block_location,
    (b.start_time + INTERVAL '5.5 hours') AS start_time, (b.end_time + INTERVAL '5.5 hours') AS end_time
  FROM allo_consultations.appointment_blocks b
  LEFT JOIN allo_persons.providers p ON b.provider_id=p.id
  LEFT JOIN allo_consultations.appointment_block_type_maps ab ON b.id=ab.appointment_block_id
  LEFT JOIN allo_health.locations l ON l.id=ab.offline_location_id
  WHERE b.is_bookable=1 AND b.deleted_at IS NULL AND ab.offline_location_id IS NOT NULL AND ab.deleted_at IS NULL
    AND DATE(b.start_time + INTERVAL '5.5 hours') >= DATEADD(month,-4,CURRENT_DATE)
    AND DATE(b.start_time + INTERVAL '5.5 hours') <= CURRENT_DATE-1),
roster_daily AS (
  SELECT dt, city, locality, block_location, pro_name,
    SUM(DATEDIFF(minute, start_time, end_time)) AS opened_mins
  FROM doctor_sessions GROUP BY 1,2,3,4,5),
sc_daily AS (
  SELECT dt, doctor_name, block_location, SUM(slot_mins) AS sc_mins, COUNT(DISTINCT start_ts) AS sc_slots FROM (
    SELECT DISTINCT CAST(DATEADD(minute,330,rs.start_time) AS DATE) AS dt, pro.name AS doctor_name, l.name AS block_location,
      DATEADD(minute,330,rs.start_time) AS start_ts, DATEDIFF(minute,rs.start_time,rs.end_time) AS slot_mins
    FROM allo_consultations.roster_slots rs
    LEFT JOIN allo_persons.providers pro ON rs.provider_id=pro.id
    LEFT JOIN (SELECT DISTINCT *, COALESCE(offline_location_id,online_location_id) AS blid FROM allo_consultations.appointment_block_type_maps WHERE deleted_at IS NULL) abtm ON rs.block_id=abtm.appointment_block_id
    LEFT JOIN allo_health.locations l ON abtm.blid=l.id
    WHERE abtm.blid=rs.location_id AND rs.type_id={SC_TYPE}
      AND DATEADD(minute,330,rs.start_time) >= DATEADD(month,-4,CURRENT_DATE) AND DATEADD(minute,330,rs.start_time) < CURRENT_DATE
      AND rs.overlaps_non_bookable_block=0 AND rs.is_realized=1
      AND ((rs.is_booked=1 AND rs.overlaps_other_booked_type=0) OR (rs.available_for_booking=1 AND rs.in_repeat_boundary=0))
      AND abtm.offline_location_id IS NOT NULL AND rs.location_id != {TELE1}
  ) GROUP BY 1,2,3),
rpt_daily AS (
  SELECT dt, doctor_name, block_location, COUNT(DISTINCT start_ts) AS rpt_slots FROM (
    SELECT DISTINCT CAST(DATEADD(minute,330,rs.start_time) AS DATE) AS dt, pro.name AS doctor_name, l.name AS block_location, DATEADD(minute,330,rs.start_time) AS start_ts
    FROM allo_consultations.roster_slots rs
    LEFT JOIN allo_persons.providers pro ON rs.provider_id=pro.id
    LEFT JOIN (SELECT DISTINCT *, COALESCE(offline_location_id,online_location_id) AS blid FROM allo_consultations.appointment_block_type_maps WHERE deleted_at IS NULL) abtm ON rs.block_id=abtm.appointment_block_id
    LEFT JOIN allo_health.locations l ON abtm.blid=l.id
    WHERE abtm.blid=rs.location_id AND rs.type_id={RPT_TYPE}
      AND DATEADD(minute,330,rs.start_time) >= DATEADD(month,-4,CURRENT_DATE) AND DATEADD(minute,330,rs.start_time) < CURRENT_DATE
      AND rs.overlaps_non_bookable_block=0 AND rs.is_realized=1
      AND ((rs.is_booked=1 AND rs.overlaps_other_booked_type=0) OR (rs.available_for_booking=1 AND rs.in_repeat_boundary=1))
      AND abtm.offline_location_id IS NOT NULL AND rs.location_id != {TELE1}
  ) GROUP BY 1,2,3),
attend_daily AS (   -- clinic-days actually WORKED = ≥1 completed offline consult (SC or FU) that day
  SELECT DISTINCT DATE(apt.start_time + INTERVAL '5.5 hours') AS dt, l.city, l.locality
  FROM allo_consultations.appointments apt
  JOIN allo_health.locations l ON apt.location_id=l.id AND l.deleted_at IS NULL
  WHERE apt.deleted_at IS NULL AND apt.status IN ('COMPLETED','RECONSULTED')
    AND lower(l.name) NOT LIKE '%online%'
    AND DATE(apt.start_time + INTERVAL '5.5 hours') >= DATEADD(month,-4,CURRENT_DATE)
    AND DATE(apt.start_time + INTERVAL '5.5 hours') <= CURRENT_DATE-1),
per_doc AS (
  SELECT r.city, r.locality, r.dt, r.pro_name,
    r.opened_mins,
    COALESCE(sc.sc_mins,0) AS net_sc_mins, COALESCE(sc.sc_slots,0) AS net_sc_slots,
    COALESCE(rpt.rpt_slots,0) AS net_rpt_slots
  FROM roster_daily r
  LEFT JOIN sc_daily sc ON r.dt=sc.dt AND r.pro_name=sc.doctor_name AND r.block_location=sc.block_location
  LEFT JOIN rpt_daily rpt ON r.dt=rpt.dt AND r.pro_name=rpt.doctor_name AND r.block_location=rpt.block_location)
SELECT p.city, p.locality, date_trunc('week', p.dt)::date AS week_start, EXTRACT(dow FROM p.dt) AS dow, p.dt,
  SUM(p.opened_mins) AS opened_mins, SUM(p.net_sc_mins) AS net_sc_mins,
  SUM(p.net_sc_slots) AS net_sc_slots, SUM(p.net_rpt_slots) AS net_rpt_slots,
  MAX(CASE WHEN ad.dt IS NOT NULL THEN 1 ELSE 0 END) AS attended
FROM per_doc p
LEFT JOIN attend_daily ad ON p.city=ad.city AND COALESCE(p.locality,'')=COALESCE(ad.locality,'') AND p.dt=ad.dt
GROUP BY 1,2,3,4,5 ORDER BY 1,2,3;
"""


def run(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("query failed:\n" + (p.stderr or "")[:800] + "\n"); sys.exit(1)
    return [ln.split("\t") for ln in p.stdout.strip().splitlines() if ln.strip()]


def main():
    rows = run(SQL)
    weeks = sorted({r[2] for r in rows})
    widx = {w: i for i, w in enumerate(weeks)}
    NW = len(weeks)
    FIELDS = ["opened_hrs", "net_sc_hrs", "net_sc_slots", "net_rpt_slots", "active_days", "wkday_days", "wkend_days",
              "attend_days", "attend_wkday", "attend_wkend"]

    clinics = {}
    for r in rows:
        city, loc, wk, dow = r[0], r[1], r[2], int(float(r[3]))
        opened_mins, sc_mins, sc_slots, rpt_slots = (float(r[5]), float(r[6]), float(r[7]), float(r[8]))
        attended = int(float(r[9])) if len(r) > 9 and r[9] != "" else 0
        key = f"{city}|{loc}"
        o = clinics.setdefault(key, {f: [0.0]*NW for f in FIELDS})
        i = widx[wk]
        o["opened_hrs"][i] += opened_mins/60.0
        o["net_sc_hrs"][i] += sc_mins/60.0
        o["net_sc_slots"][i] += sc_slots
        o["net_rpt_slots"][i] += rpt_slots
        o["active_days"][i] += 1
        if dow in (0, 6):   # Redshift EXTRACT(dow): 0=Sun,6=Sat
            o["wkend_days"][i] += 1
            o["attend_wkend"][i] += attended
        else:
            o["wkday_days"][i] += 1
            o["attend_wkday"][i] += attended
        o["attend_days"][i] += attended   # days actually WORKED (≥1 completed consult) — attendance-based

    # round for compactness
    for o in clinics.values():
        for f in ("opened_hrs", "net_sc_hrs"):
            o[f] = [round(x, 1) for x in o[f]]
        for f in ("net_sc_slots", "net_rpt_slots", "active_days", "wkday_days", "wkend_days",
                  "attend_days", "attend_wkday", "attend_wkend"):
            o[f] = [int(round(x)) for x in o[f]]

    out = {"_meta": {"weeks": weeks, "source": "L2 Roster & Slots · realized SC/RPT capacity + roster days",
                     "note": "net_sc_slots = utilisation denominator (done/slots). active_days = ROSTERED days (opened). "
                             "attend_days = days actually WORKED (≥1 completed offline consult) — matches city-head attendance view; wkend/wkday split too.",
                     "fields": FIELDS}, "clinics": clinics}
    json.dump(out, open(os.path.join(ROOT, "data_availability.json"), "w"), separators=(",", ":"))
    vwk = "2026-06-22"

    def cs(city, f):
        return sum(o[f][widx[vwk]] for k, o in clinics.items() if k.split("|")[0] == city) if vwk in widx else 0
    print(f"data_availability.json · {len(clinics)} clinics · {NW} weeks ({weeks[0]}→{weeks[-1]})")
    print(f"\n── verify {vwk} (L2 roster targets: BLR opened 445 netSC 267hr / MUM 263,141 / CHN 155,95) ──")
    for c in ["Bangalore", "Mumbai", "Hyderabad", "Chennai", "Pune"]:
        print(f"  {c:11} opened {cs(c,'opened_hrs'):7.0f}  net_sc_hr {cs(c,'net_sc_hrs'):7.1f}  sc_slots {cs(c,'net_sc_slots'):5}  rostered_days {cs(c,'active_days'):3}  attended_days {cs(c,'attend_days'):3}")
    bkey = next((k for k in clinics if k.split("|")[0] == "Pune" and "aner" in k), None)
    if bkey and vwk in widx:
        j = widx[vwk]; o = clinics[bkey]
        print(f"\n── Baner {vwk}: rostered {o['active_days'][j]}d (wd {o['wkday_days'][j]}/we {o['wkend_days'][j]})  "
              f"ATTENDED {o['attend_days'][j]}d (wd {o['attend_wkday'][j]}/we {o['attend_wkend'][j]})  [sheet weekend expect 0] ──")


if __name__ == "__main__":
    main()
