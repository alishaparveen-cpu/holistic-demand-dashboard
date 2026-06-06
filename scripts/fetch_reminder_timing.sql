-- Does reminder TIMING affect show-up? For each resolved Screening Call (completed or missed),
-- find the last reminder sent BEFORE the appointment, bucket the lead time, and measure show-up
-- per bucket. Network-level. Tells us the most effective time to send reminders.
WITH sc AS (
  SELECT a.id, LOWER(a.status) AS st, a.start_time
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  WHERE a.deleted_at IS NULL
    AND a.start_time >= '2026-04-06' AND a.start_time < '2026-06-01'
    AND LOWER(a.status) IN ('completed','reconsulted','missed')
    AND LOWER(COALESCE(loc.locality,'')) <> 'online' AND loc.locality IS NOT NULL
),
last_rem AS (
  SELECT sc.id, MAX(w.created_at) AS lr
  FROM sc
  JOIN allo_vendors.whatsapp w
    ON w.reference_id = sc.id AND w.reference_entity='appointment'
   AND w.template ILIKE '%reminder%' AND w.deleted_at IS NULL
   AND w.created_at < sc.start_time
  GROUP BY sc.id
)
SELECT
  CASE WHEN lr.lr IS NULL THEN '4_none'
       WHEN DATEDIFF(hour, lr.lr, sc.start_time) >= 24 THEN '1_gte24h'
       WHEN DATEDIFF(hour, lr.lr, sc.start_time) >= 6  THEN '2_6to24h'
       ELSE '3_lt6h' END AS bucket,
  COUNT(*) AS total,
  SUM(CASE WHEN sc.st IN ('completed','reconsulted') THEN 1 ELSE 0 END) AS done,
  SUM(CASE WHEN sc.st = 'missed' THEN 1 ELSE 0 END) AS missed
FROM sc LEFT JOIN last_rem lr ON lr.id = sc.id
GROUP BY 1 ORDER BY 1;
