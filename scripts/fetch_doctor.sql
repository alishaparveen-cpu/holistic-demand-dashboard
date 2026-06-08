-- Clinic Scorecard — per clinic / DOCTOR / week: availability (scheduled / shrunk / available
-- slots from roster_slots) + outcomes (booked / done / missed from appointments). Lets a clinic
-- view split availability and performance by doctor. Joined to provider name.
WITH ros AS (
  SELECT loc.city AS city, COALESCE(loc.locality,loc.name,'') AS clinic, rs.provider_id,
         TO_CHAR(DATE_TRUNC('week', rs.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
         rs.start_time,
         BOOL_OR(ab.id IS NOT NULL) AS is_shrinkage
  FROM allo_consultations.roster_slots rs
  JOIN allo_health.locations loc ON loc.id = rs.location_id AND loc.deleted_at IS NULL
  LEFT JOIN allo_consultations.appointment_blocks ab
    ON ab.provider_id = rs.provider_id AND ab.is_bookable = false AND ab.deleted_at IS NULL
   AND ab.start_time < rs.end_time AND ab.end_time > rs.start_time
  WHERE rs.type_id = 'cd02525c-1528-4047-a12c-1ad526c28c9a'
    AND rs.start_time >= '2026-04-20' AND rs.start_time < '2026-06-08'
    AND LOWER(COALESCE(loc.locality,loc.name,'')) NOT IN ('','online')
  GROUP BY 1,2,3,4, rs.start_time
),
ros_agg AS (
  SELECT city, clinic, provider_id, wk,
         COUNT(*) AS sched, COUNT(CASE WHEN is_shrinkage THEN 1 END) AS shrunk,
         COUNT(CASE WHEN NOT is_shrinkage THEN 1 END) AS avail
  FROM ros GROUP BY 1,2,3,4
),
app AS (
  SELECT loc.city AS city, loc.locality AS clinic, a.provider_id,
         TO_CHAR(DATE_TRUNC('week', a.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
         COUNT(*) AS total,
         SUM(CASE WHEN LOWER(a.status) IN ('completed','reconsulted') THEN 1 ELSE 0 END) AS done,
         SUM(CASE WHEN LOWER(a.status)='missed' THEN 1 ELSE 0 END) AS missed
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  WHERE a.deleted_at IS NULL AND a.start_time>='2026-04-20' AND a.start_time<'2026-06-08'
    AND LOWER(COALESCE(loc.locality,'')) NOT IN ('','online') AND loc.locality IS NOT NULL
  GROUP BY 1,2,3,4
)
SELECT COALESCE(r.city,a.city) AS city, COALESCE(r.clinic,a.clinic) AS clinic,
  COALESCE(p.name,'Unknown') AS doctor, COALESCE(r.wk,a.wk) AS wk,
  COALESCE(r.sched,0) AS sched, COALESCE(r.shrunk,0) AS shrunk, COALESCE(r.avail,0) AS avail,
  COALESCE(a.total,0) AS total, COALESCE(a.done,0) AS done, COALESCE(a.missed,0) AS missed
FROM ros_agg r
FULL OUTER JOIN app a ON a.city=r.city AND a.clinic=r.clinic AND a.provider_id=r.provider_id AND a.wk=r.wk
LEFT JOIN allo_persons.providers p ON p.id = COALESCE(r.provider_id, a.provider_id)
WHERE COALESCE(r.clinic,a.clinic) IS NOT NULL
ORDER BY 1,2,3,4;
