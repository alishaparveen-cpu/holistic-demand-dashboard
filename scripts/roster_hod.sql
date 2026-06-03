-- HOUR-OF-DAY x DOW grid per clinic/week — for the availability heatmap
WITH s AS (
  SELECT loc.city AS city, COALESCE(loc.locality,loc.name,'') AS clinic,
         TO_CHAR(DATE_TRUNC('week', rs.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
         EXTRACT(HOUR FROM rs.start_time + INTERVAL '5.5 hours') AS hod,
         DATE_TRUNC('hour', rs.start_time + INTERVAL '5.5 hours') AS hr_ist
  FROM allo_consultations.roster_slots rs
  JOIN allo_health.locations loc ON loc.id = rs.location_id AND loc.deleted_at IS NULL
  WHERE rs.type_id = 'cd02525c-1528-4047-a12c-1ad526c28c9a'
    AND rs.available_for_booking = 1
    AND rs.start_time >= '2026-03-09' AND rs.start_time < '2026-06-01'
    AND COALESCE(loc.locality,loc.name,'') <> ''
    AND LOWER(COALESCE(loc.locality,loc.name,'')) <> 'online'
  GROUP BY 1,2,3,4,5
)
SELECT city, clinic, wk, hod, COUNT(*) AS hrs_covered
FROM s GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;
