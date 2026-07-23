-- Per-DOCTOR weekly availability, per clinic (city, locality):
--   rostered day  = provider had >=1 bookable offline appointment_block that day
--   attended day  = provider completed >=1 offline consult (COMPLETED/RECONSULTED) that day
--   opened_hrs    = bookable block hours; shrink_hrs = hours lost to overlapping non-bookable (shrinkage) blocks
-- Shrinkage split logic mirrors the org's canonical slot query, per provider.
WITH sess AS (
  SELECT b.provider_id, p.name AS pro_name, l.city, l.locality,
    DATE(b.start_time + INTERVAL '5.5 hours') AS dt,
    (b.start_time + INTERVAL '5.5 hours') AS st, (b.end_time + INTERVAL '5.5 hours') AS et,
    EXTRACT(hour FROM (b.start_time + INTERVAL '5.5 hours')) AS sh,   -- session start hour (IST), for AM/PM shift split
    DATEDIFF(minute, b.start_time, b.end_time) AS mins
  FROM allo_consultations.appointment_blocks b
  JOIN allo_persons.providers p ON b.provider_id=p.id
  JOIN allo_consultations.appointment_block_type_maps ab ON b.id=ab.appointment_block_id AND ab.deleted_at IS NULL AND ab.offline_location_id IS NOT NULL
  JOIN allo_health.locations l ON l.id=ab.offline_location_id AND l.deleted_at IS NULL
  WHERE b.is_bookable=1 AND b.deleted_at IS NULL
    AND DATE(b.start_time + INTERVAL '5.5 hours') >= DATEADD(month,-7,CURRENT_DATE)
    AND DATE(b.start_time + INTERVAL '5.5 hours') <= CURRENT_DATE-1),
numbers AS (SELECT ROW_NUMBER() OVER () - 1 AS num FROM (SELECT NULL FROM allo_consultations.appointment_blocks LIMIT 250) t),
expanded_dates AS (SELECT CURRENT_DATE - 1 - num AS dt FROM numbers),
shr_raw AS (SELECT b.provider_id, b.start_time + INTERVAL '5.5 hours' AS ss, b.end_time + INTERVAL '5.5 hours' AS se
  FROM allo_consultations.appointment_blocks b WHERE b.is_bookable=0 AND b.deleted_at IS NULL),
shr_exp AS (SELECT DISTINCT ed.dt, sr.provider_id, GREATEST(sr.ss, ed.dt) AS ss,
    CASE WHEN sr.se::TIME = TIME '00:00:00' THEN sr.se::DATE - 1 + TIME '23:59:59' ELSE sr.se END AS se
  FROM shr_raw sr JOIN expanded_dates ed ON ed.dt BETWEEN sr.ss::DATE AND sr.se::DATE),
shrink AS (SELECT s.dt, s.provider_id, s.city, s.locality,
    SUM(DATEDIFF(minute, GREATEST(se.ss, s.st), LEAST(se.se, s.et))) AS shr_mins
  FROM sess s JOIN shr_exp se ON se.provider_id=s.provider_id AND se.dt=s.dt AND se.ss < s.et AND se.se > s.st
  WHERE GREATEST(se.ss, s.st) < LEAST(se.se, s.et) GROUP BY 1,2,3,4),
oh AS (SELECT dt, provider_id, pro_name, city, locality, SUM(mins) AS opened_mins,
    SUM(CASE WHEN sh < 12 THEN mins ELSE 0 END) AS am_mins,               -- morning slots (start < 12:00)
    SUM(CASE WHEN sh >= 12 AND sh < 16 THEN mins ELSE 0 END) AS noon_mins, -- afternoon slots (12:00–15:59)
    SUM(CASE WHEN sh >= 16 THEN mins ELSE 0 END) AS pm_mins                -- evening slots (>= 16:00)
  FROM sess GROUP BY 1,2,3,4,5),
oh_shr AS (SELECT o.dt, o.pro_name, o.city, o.locality, o.opened_mins, o.am_mins, o.noon_mins, o.pm_mins, COALESCE(sh.shr_mins,0) AS shr_mins
  FROM oh o LEFT JOIN shrink sh ON sh.dt=o.dt AND sh.provider_id=o.provider_id AND sh.city=o.city AND COALESCE(sh.locality,'')=COALESCE(o.locality,'')),
att AS (
  SELECT DISTINCT DATE(apt.start_time + INTERVAL '5.5 hours') AS dt, p.name AS pro_name, l.city, l.locality
  FROM allo_consultations.appointments apt
  JOIN allo_health.locations l ON apt.location_id=l.id AND l.deleted_at IS NULL
  JOIN allo_persons.providers p ON apt.provider_id=p.id
  WHERE apt.deleted_at IS NULL AND apt.status IN ('COMPLETED','RECONSULTED') AND lower(l.name) NOT LIKE '%online%'
    AND DATE(apt.start_time + INTERVAL '5.5 hours') >= DATEADD(month,-7,CURRENT_DATE)
    AND DATE(apt.start_time + INTERVAL '5.5 hours') <= CURRENT_DATE-1),
u AS (
  SELECT COALESCE(os.dt,a.dt) AS dt, COALESCE(os.pro_name,a.pro_name) AS pro_name,
    COALESCE(os.city,a.city) AS city, COALESCE(os.locality,a.locality) AS locality,
    CASE WHEN os.dt IS NOT NULL THEN 1 ELSE 0 END AS rostered,
    CASE WHEN a.dt IS NOT NULL THEN 1 ELSE 0 END AS attended,
    COALESCE(os.opened_mins,0) AS opened_mins, COALESCE(os.shr_mins,0) AS shr_mins,
    COALESCE(os.am_mins,0) AS am_mins, COALESCE(os.noon_mins,0) AS noon_mins, COALESCE(os.pm_mins,0) AS pm_mins
  FROM oh_shr os FULL OUTER JOIN att a
    ON os.dt=a.dt AND os.pro_name=a.pro_name AND os.city=a.city AND COALESCE(os.locality,'')=COALESCE(a.locality,''))
SELECT city, locality, pro_name, date_trunc('week', dt)::date AS week_start,
  SUM(rostered) AS rost_days,
  SUM(CASE WHEN EXTRACT(dow FROM dt) IN (0,6) THEN rostered ELSE 0 END) AS rost_wend,
  SUM(CASE WHEN EXTRACT(dow FROM dt) NOT IN (0,6) THEN rostered ELSE 0 END) AS rost_wday,
  SUM(attended) AS att_days,
  SUM(CASE WHEN EXTRACT(dow FROM dt) IN (0,6) THEN attended ELSE 0 END) AS att_wend,
  SUM(CASE WHEN EXTRACT(dow FROM dt) NOT IN (0,6) THEN attended ELSE 0 END) AS att_wday,
  ROUND(SUM(opened_mins)/60.0, 2) AS opened_hrs,
  ROUND(SUM(shr_mins)/60.0, 2) AS shrink_hrs,
  ROUND(SUM(am_mins)/60.0, 2) AS am_hrs,        -- morning bookable hours (shift-timing split)
  ROUND(SUM(noon_mins)/60.0, 2) AS noon_hrs,    -- afternoon bookable hours
  ROUND(SUM(pm_mins)/60.0, 2) AS pm_hrs         -- evening bookable hours
FROM u
GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;
