WITH hrs AS (
  SELECT loc.city city, COALESCE(loc.locality,loc.name,'') clinic,
    TO_CHAR(DATE_TRUNC('week', rs.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') wk,
    DATE_TRUNC('hour', rs.start_time + INTERVAL '5.5 hours') hr_ist,
    EXTRACT(DOW FROM rs.start_time + INTERVAL '5.5 hours') dow
  FROM allo_consultations.roster_slots rs
  JOIN allo_health.locations loc ON loc.id=rs.location_id AND loc.deleted_at IS NULL
  WHERE rs.type_id='cd02525c-1528-4047-a12c-1ad526c28c9a' AND rs.available_for_booking=1
    AND rs.start_time >= '2026-03-16' AND rs.start_time < '2026-06-08'
    AND COALESCE(loc.locality,loc.name,'') <> '' AND LOWER(COALESCE(loc.locality,loc.name,'')) <> 'online'
  GROUP BY 1,2,3,4,5
)
SELECT city, clinic, wk, dow, COUNT(*) hrs
FROM hrs GROUP BY 1,2,3,4 ORDER BY 1,2,3,4
