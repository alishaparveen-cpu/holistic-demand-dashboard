-- Per clinic × WEEK: scheduled/shrunk(blocked)/available slots by day-of-week × hour (IST), last 12 weeks.
WITH slots AS (
  SELECT loc.city AS city, COALESCE(loc.locality,loc.name,'') AS clinic,
    TO_CHAR(DATE_TRUNC('week', rs.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
    EXTRACT(dow FROM rs.start_time + INTERVAL '5.5 hours')::int AS dow,
    EXTRACT(hour FROM rs.start_time + INTERVAL '5.5 hours')::int AS hr,
    rs.provider_id, rs.start_time, BOOL_OR(ab.id IS NOT NULL) AS is_shrunk
  FROM allo_consultations.roster_slots rs
  JOIN allo_health.locations loc ON loc.id=rs.location_id AND loc.deleted_at IS NULL
  LEFT JOIN allo_consultations.appointment_blocks ab
    ON ab.provider_id=rs.provider_id AND ab.is_bookable=false AND ab.deleted_at IS NULL
   AND ab.start_time < rs.end_time AND ab.end_time > rs.start_time
  WHERE rs.type_id='cd02525c-1528-4047-a12c-1ad526c28c9a'
    AND rs.start_time >= '2026-03-16' AND rs.start_time < '2026-06-08'
    AND COALESCE(loc.locality,loc.name,'')<>'' AND LOWER(COALESCE(loc.locality,loc.name,''))<>'online'
  GROUP BY 1,2,3,4,5, rs.provider_id, rs.start_time
)
SELECT city||'|'||clinic AS k, wk, dow, hr,
  COUNT(*) AS sched, COUNT(CASE WHEN is_shrunk THEN 1 END) AS shrunk,
  COUNT(CASE WHEN NOT is_shrunk THEN 1 END) AS avail
FROM slots GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;
