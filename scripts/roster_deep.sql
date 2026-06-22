-- DEEPER ROSTER PULL: slots + hours + hour-of-day, per clinic/week
-- (Screening-Call, bookable). Run after: aws sso login --profile redshift-data
WITH s AS (
  SELECT loc.city AS city,
         COALESCE(loc.locality,loc.name,'') AS clinic,
         TO_CHAR(DATE_TRUNC('week', rs.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
         rs.start_time + INTERVAL '5.5 hours' AS ist,
         EXTRACT(HOUR FROM rs.start_time + INTERVAL '5.5 hours') AS hod,
         EXTRACT(DOW  FROM rs.start_time + INTERVAL '5.5 hours') AS dow,
         rs.id AS slot_id
  FROM allo_consultations.roster_slots rs
  JOIN allo_health.locations loc ON loc.id = rs.location_id AND loc.deleted_at IS NULL
  WHERE rs.type_id = 'cd02525c-1528-4047-a12c-1ad526c28c9a'   -- Screening Call
    AND rs.available_for_booking = 1
    AND rs.start_time >= '2026-04-27' AND rs.start_time < '2026-06-22'
    AND COALESCE(loc.locality,loc.name,'') <> ''
    AND LOWER(COALESCE(loc.locality,loc.name,'')) <> 'online'
)
SELECT city, clinic, wk,
       COUNT(*)                                           AS slots,        -- bookable slot count
       COUNT(DISTINCT DATE_TRUNC('hour', ist))            AS hrs,          -- distinct bookable hours
       COUNT(DISTINCT DATE_TRUNC('day',  ist))            AS days,         -- active days (sanity vs tracker)
       SUM(CASE WHEN dow IN (0,6) THEN 1 ELSE 0 END)      AS we_slots,     -- weekend slots
       MIN(hod) AS first_hr, MAX(hod) AS last_hr          -- coverage window
FROM s
GROUP BY 1,2,3
ORDER BY 1,2,3;
