#!/usr/bin/env python3
"""Accurate per-clinic weekly AVAILABILITY from the roster, matching the ops roster methodology:
  Opened hours (bookable appointment_blocks) → − Shrinkage (is_bookable=0 blocks overlapping)
  = Opened After Shrinkage; plus realized NET available consult hours split SC vs FU (roster_slots,
  is_realized=1). Active days = days the clinic was open >1h after shrinkage, split weekday/weekend.

Returns DAY-level rows (dt, city, locality, opened/shrink/sc/fu mins); Python rolls up to the master
week grid and counts active weekday/weekend days. Writes clinic['avail_roster'] =
  {opened,shrink,after_shrink,sc_net,fu_net,net_avail,dead,active_wkday,active_wkend} (each [weeks]).
Run: AWS_PROFILE=redshift-data python3 scripts/build_avail_roster.py
"""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(__file__))
import patch_subcat as PS
ROOT = PS.ROOT; OUT = os.path.join(ROOT, "data_source_recon.json")
idx = PS.idx; Z = PS.Z; run_sql = PS.run_sql
SC_TYPE = "cd02525c-1528-4047-a12c-1ad526c28c9a"; RPT_TYPE = "871a9ff6-e076-4fef-9aee-14c566e67d71"
TELE = "c7d8c9d2-f389-4e8f-a260-71110195b83f"
ACTIVE_MIN = 60   # a day counts as "active" if opened-after-shrinkage > 1 hour

SQL = f"""WITH numbers AS (SELECT ROW_NUMBER() OVER () - 1 AS num FROM (SELECT NULL FROM allo_consultations.appointment_blocks LIMIT 150) t1),
expanded_dates AS (SELECT CURRENT_DATE - 1 - num AS dt FROM numbers WHERE CURRENT_DATE - 1 - num >= DATEADD(month, -3, CURRENT_DATE)),
doctor_sessions AS (
    SELECT DISTINCT DATE(b.start_time + INTERVAL '5 HOURS 30 MINUTES') AS dt, p.name AS pro_name, l.city AS city, l.locality AS locality,
        l.name AS block_location, (b.start_time + INTERVAL '5 HOURS 30 MINUTES') AS start_time, (b.end_time + INTERVAL '5 HOURS 30 MINUTES') AS end_time
    FROM allo_consultations.appointment_blocks b
    LEFT JOIN allo_persons.providers p ON b.provider_id = p.id
    LEFT JOIN allo_consultations.appointment_block_type_maps ab ON b.id = ab.appointment_block_id
    LEFT JOIN allo_health.locations l ON l.id = ab.offline_location_id
    WHERE b.is_bookable = 1 AND b.deleted_at IS NULL AND ab.offline_location_id IS NOT NULL AND ab.deleted_at IS NULL
      AND DATE(b.start_time + INTERVAL '5 HOURS 30 MINUTES') >= DATEADD(month, -3, CURRENT_DATE)
      AND DATE(b.start_time + INTERVAL '5 HOURS 30 MINUTES') <= CURRENT_DATE - 1),
shrinkage_raw AS (SELECT p.name AS pro_name, b.start_time + INTERVAL '5 HOURS 30 MINUTES' AS shrink_start,
        CASE WHEN CAST(b.end_time + INTERVAL '5 HOURS 30 MINUTES' AS TIME) = TIME '00:00:00' THEN DATEADD(second, -1, DATE(b.end_time + INTERVAL '5 HOURS 30 MINUTES'))::TIMESTAMP ELSE b.end_time + INTERVAL '5 HOURS 30 MINUTES' END AS shrink_end
    FROM allo_consultations.appointment_blocks b LEFT JOIN allo_persons.providers p ON b.provider_id = p.id WHERE b.is_bookable = 0 AND b.deleted_at IS NULL),
shrinkage_expanded AS (SELECT DISTINCT ed.dt AS shrink_dt, sr.pro_name, GREATEST(sr.shrink_start, ed.dt::TIMESTAMP) AS shrink_start, LEAST(sr.shrink_end, DATEADD(day, 1, ed.dt)::TIMESTAMP) AS shrink_end
    FROM shrinkage_raw sr JOIN expanded_dates ed ON ed.dt BETWEEN sr.shrink_start::DATE AND sr.shrink_end::DATE),
valid_shrinkage AS (SELECT DISTINCT se.shrink_dt AS dt, se.pro_name, ds.block_location, ds.start_time AS working_start_time,
        GREATEST(se.shrink_start, ds.start_time) AS shrink_start_time, LEAST(se.shrink_end, ds.end_time) AS shrink_end_time
    FROM shrinkage_expanded se JOIN doctor_sessions ds ON se.pro_name = ds.pro_name AND se.shrink_dt = ds.dt AND se.shrink_start < ds.end_time AND se.shrink_end > ds.start_time),
shrinkage_per_session AS (SELECT dt, pro_name, block_location, working_start_time, SUM(DATEDIFF(minute, shrink_start_time, shrink_end_time)) AS shrink_mins
    FROM valid_shrinkage WHERE shrink_start_time < shrink_end_time GROUP BY 1,2,3,4),
roster_daily AS (SELECT ds.dt, ds.city, ds.locality, ds.block_location, ds.pro_name,
        SUM(DATEDIFF(minute, ds.start_time, ds.end_time)) AS roster_opened_mins, SUM(COALESCE(sps.shrink_mins, 0)) AS shrinkage_mins
    FROM doctor_sessions ds LEFT JOIN shrinkage_per_session sps ON ds.pro_name = sps.pro_name AND ds.dt = sps.dt AND ds.block_location = sps.block_location AND ds.start_time = sps.working_start_time
    GROUP BY 1,2,3,4,5),
sc_daily AS (SELECT dt, doctor_name, block_location, SUM(slot_mins) AS sc_mins FROM (
        SELECT DISTINCT CAST(DATEADD(minute, 330, rs.start_time) AS DATE) AS dt, pro.name AS doctor_name, l.name AS block_location,
            DATEADD(minute, 330, rs.start_time) AS start_ts, DATEDIFF(minute, rs.start_time, rs.end_time) AS slot_mins
        FROM allo_consultations.roster_slots rs LEFT JOIN allo_persons.providers pro ON rs.provider_id = pro.id
        LEFT JOIN (SELECT DISTINCT *, COALESCE(offline_location_id, online_location_id) AS block_location_id FROM allo_consultations.appointment_block_type_maps WHERE deleted_at IS NULL) abtm ON rs.block_id = abtm.appointment_block_id
        LEFT JOIN allo_health.locations l ON abtm.block_location_id = l.id
        WHERE abtm.block_location_id = rs.location_id AND rs.type_id = '{SC_TYPE}'
          AND DATEADD(minute, 330, rs.start_time) >= DATEADD(month, -3, CURRENT_DATE) AND DATEADD(minute, 330, rs.start_time) < CURRENT_DATE
          AND rs.overlaps_non_bookable_block = 0 AND rs.is_realized = 1
          AND ((rs.is_booked = 1 AND rs.overlaps_other_booked_type = 0) OR (rs.available_for_booking = 1 AND rs.in_repeat_boundary = 0))
          AND abtm.offline_location_id IS NOT NULL AND rs.location_id != '{TELE}') sub GROUP BY 1,2,3),
rpt_daily AS (SELECT dt, doctor_name, block_location, SUM(slot_mins) AS rpt_mins FROM (
        SELECT DISTINCT CAST(DATEADD(minute, 330, rs.start_time) AS DATE) AS dt, pro.name AS doctor_name, l.name AS block_location,
            DATEADD(minute, 330, rs.start_time) AS start_ts, DATEDIFF(minute, rs.start_time, rs.end_time) AS slot_mins
        FROM allo_consultations.roster_slots rs LEFT JOIN allo_persons.providers pro ON rs.provider_id = pro.id
        LEFT JOIN (SELECT DISTINCT *, COALESCE(offline_location_id, online_location_id) AS block_location_id FROM allo_consultations.appointment_block_type_maps WHERE deleted_at IS NULL) abtm ON rs.block_id = abtm.appointment_block_id
        LEFT JOIN allo_health.locations l ON abtm.block_location_id = l.id
        WHERE abtm.block_location_id = rs.location_id AND rs.type_id = '{RPT_TYPE}'
          AND DATEADD(minute, 330, rs.start_time) >= DATEADD(month, -3, CURRENT_DATE) AND DATEADD(minute, 330, rs.start_time) < CURRENT_DATE
          AND rs.overlaps_non_bookable_block = 0 AND rs.is_realized = 1
          AND ((rs.is_booked = 1 AND rs.overlaps_other_booked_type = 0) OR (rs.available_for_booking = 1 AND rs.in_repeat_boundary = 1))
          AND abtm.offline_location_id IS NOT NULL AND rs.location_id != '{TELE}') sub GROUP BY 1,2,3),
final AS (SELECT r.dt, r.city, r.locality, r.pro_name AS doctor_name, r.block_location, r.roster_opened_mins, r.shrinkage_mins,
        COALESCE(sc.sc_mins,0) AS net_sc_mins, COALESCE(rpt.rpt_mins,0) AS net_rpt_mins
    FROM roster_daily r
    LEFT JOIN sc_daily sc ON r.dt = sc.dt AND r.pro_name = sc.doctor_name AND r.block_location = sc.block_location
    LEFT JOIN rpt_daily rpt ON r.dt = rpt.dt AND r.pro_name = rpt.doctor_name AND r.block_location = rpt.block_location)
SELECT TO_CHAR(dt,'YYYY-MM-DD') dt, city, locality, doctor_name,
  SUM(roster_opened_mins) opened_min, SUM(shrinkage_mins) shrink_min, SUM(net_sc_mins) sc_min, SUM(net_rpt_mins) fu_min
FROM final GROUP BY 1,2,3,4;"""

def slugify(loc, city):
    s = lambda x: "".join(ch if ch.isalnum() else "_" for ch in (x or "").strip().lower())
    return s(loc) + "_" + s(city)
CITY_ALIAS = {"bengaluru": "bangalore", "gurgaon": "gurugram"}
def norm_city(c): c = (c or "").strip().lower(); return CITY_ALIAS.get(c, c)
def wk_of(dt):   # Monday-week ISO string
    d = datetime.date.fromisoformat(dt); return (d - datetime.timedelta(days=d.weekday())).isoformat()

FIELDS = ["opened", "shrink", "after_shrink", "sc_net", "fu_net", "net_avail", "dead", "active_wkday", "active_wkend"]
DFIELDS = ["av_after", "av_sc"]   # per-doctor availability merged into clinic.by_doctor
if __name__ == "__main__":
    d = json.load(open(OUT)); clinics = d["clinics"]
    day = {}    # (slug, dt) -> {opened,shrink,sc,fu}  (day totals across doctors → clinic rollup + active days)
    dwk = {}    # slug -> doctor -> {av_after,av_sc}   (per-doctor weekly hours)
    for line in run_sql(SQL):
        r = line.split("\t") if isinstance(line, str) else line
        if len(r) < 8: continue
        dt, city, loc, doctor, om, sm, scm, fum = r[:8]
        if not loc or loc in ("", "None"): continue
        wk = wk_of(dt)
        if wk not in idx: continue
        slug = slugify(loc, norm_city(city)); i = idx[wk]
        try: om = float(om); sm = float(sm); scm = float(scm); fum = float(fum)
        except (ValueError, TypeError): continue
        after = om - sm
        dd = day.setdefault((slug, dt), {"opened": 0.0, "shrink": 0.0, "sc": 0.0, "fu": 0.0})
        dd["opened"] += om; dd["shrink"] += sm; dd["sc"] += scm; dd["fu"] += fum
        if doctor:
            e = dwk.setdefault(slug, {}).setdefault(doctor, {f: Z() for f in DFIELDS})
            e["av_after"][i] += after / 60.0; e["av_sc"][i] += scm / 60.0

    acc = {}   # slug -> field -> [weeks]
    for (slug, dt), v in day.items():
        i = idx[wk_of(dt)]
        a = acc.setdefault(slug, {f: Z() for f in FIELDS})
        after = v["opened"] - v["shrink"]; netav = v["sc"] + v["fu"]
        a["opened"][i] += v["opened"] / 60.0; a["shrink"][i] += v["shrink"] / 60.0; a["after_shrink"][i] += after / 60.0
        a["sc_net"][i] += v["sc"] / 60.0; a["fu_net"][i] += v["fu"] / 60.0; a["net_avail"][i] += netav / 60.0
        a["dead"][i] += (after - netav) / 60.0
        if after > ACTIVE_MIN:
            dow = datetime.date.fromisoformat(dt).weekday()
            a["active_wkday" if dow <= 4 else "active_wkend"][i] += 1

    matched = 0; dmerged = 0
    for slug, c in clinics.items():
        if slug in acc:
            a = acc[slug]
            c["avail_roster"] = {f: ([round(x, 1) for x in a[f]] if f not in ("active_wkday", "active_wkend") else a[f]) for f in FIELDS}
            matched += 1
        for dr, fields in (dwk.get(slug) or {}).items():
            if not any(any(fields[f]) for f in DFIELDS): continue
            bd = c.setdefault("by_doctor", {}).setdefault(dr, {})
            for f in DFIELDS:
                if any(fields[f]): bd[f] = [round(x, 1) for x in fields[f]]; dmerged += 1
    json.dump(d, open(OUT, "w"), separators=(",", ":"))
    print("avail_roster for %d clinics (of %d) | doctor-avail merged into %d clinic-doctor fields" % (matched, len(clinics), dmerged))
    am = clinics.get("ameerpet_hyderabad", {}).get("avail_roster")
    if am:
        print("Ameerpet weeks      :", d["_meta"]["weeks"][:7])
        for f in ["after_shrink", "sc_net", "active_wkday", "active_wkend"]:
            print("  %-13s:" % f, am[f][:7])
        bd = clinics["ameerpet_hyderabad"].get("by_doctor", {})
        for dr in list(bd)[:2]:
            print("  doc %-22s av_sc=%s" % (dr[:22], bd[dr].get("av_sc", [0])[:6]))
