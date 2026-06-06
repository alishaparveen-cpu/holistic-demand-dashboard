-- Status × booking-type crosstab: each appointment status split by NEW (patient's all-time
-- first Screening Call) vs FOLLOW-UP (returning), per clinic/week. Lets us show completion /
-- no-show / reschedule RATES within new vs follow-up vs total.
WITH sc_all AS (
  SELECT a.id, a.patient_id, a.created_at, a.start_time, LOWER(a.status) AS st,
         LOWER(COALESCE(a.previous_status,'')) AS prev, loc.city, loc.locality
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  WHERE a.deleted_at IS NULL
),
firsts AS (SELECT patient_id, MIN(created_at) AS first_crt FROM sc_all GROUP BY patient_id),
j AS (
  SELECT s.city, s.locality AS clinic,
    TO_CHAR(DATE_TRUNC('week', s.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
    (s.created_at = f.first_crt) AS is_new, s.st, s.prev
  FROM sc_all s JOIN firsts f ON s.patient_id=f.patient_id
  WHERE s.start_time >= '2026-03-09' AND s.start_time < '2026-06-01'
    AND LOWER(COALESCE(s.locality,'')) <> 'online' AND s.locality IS NOT NULL
)
SELECT city, clinic, wk,
  CASE WHEN is_new THEN 'new' ELSE 'fu' END AS who,
  COUNT(*) AS total,
  SUM(CASE WHEN st IN ('completed','reconsulted') THEN 1 ELSE 0 END) AS done,
  SUM(CASE WHEN st='missed' THEN 1 ELSE 0 END) AS missed,
  SUM(CASE WHEN st='rescheduled' AND prev<>'missed' THEN 1 ELSE 0 END) AS resched_patient,
  SUM(CASE WHEN st='rescheduled' AND prev='missed' THEN 1 ELSE 0 END) AS resched_noshow,
  SUM(CASE WHEN st='cancelled' THEN 1 ELSE 0 END) AS cancelled,
  SUM(CASE WHEN st IN ('scheduled','confirmed','in_progress','provider_joined') THEN 1 ELSE 0 END) AS scheduled
FROM j
GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;
