-- The DATABASE's native breakdown of Screening-Call bookings, last 8 weeks (network).
-- status partitions the total (every appointment row has exactly one status).
-- previous_status explains the 'rescheduled' bucket. is_walkin is an orthogonal flag.
WITH sc AS (
  SELECT a.id, LOWER(a.status) AS st, LOWER(COALESCE(a.previous_status,'')) AS prev,
         COALESCE(a.is_walkin,0) AS walkin
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  WHERE a.deleted_at IS NULL
    AND a.start_time >= '2026-04-20' AND a.start_time < '2026-06-22'
    AND LOWER(COALESCE(loc.locality,'')) <> 'online' AND loc.locality IS NOT NULL
)
SELECT
  st AS status,
  CASE WHEN st='rescheduled' THEN (CASE WHEN prev='missed' THEN '(prev=missed → after no-show)' ELSE '(prev='||prev||' → by patient/ops)' END) ELSE '' END AS reschedule_origin,
  COUNT(*) AS n,
  SUM(CASE WHEN walkin THEN 1 ELSE 0 END) AS walkins
FROM sc
GROUP BY 1,2
ORDER BY n DESC;
