-- Status × booking-type crosstab: each appointment status split by NEW (patient's all-time
-- first Screening Call) vs FOLLOW-UP (returning), per clinic/week. Lets us show completion /
-- no-show / reschedule RATES within new vs follow-up vs total.
WITH sc_all AS (
  SELECT a.id, a.patient_id, a.created_at, a.start_time, LOWER(a.status) AS st,
         LOWER(COALESCE(a.previous_status,'')) AS prev, LOWER(COALESCE(a.reason,'')) AS rsn, loc.city, loc.locality
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  WHERE a.deleted_at IS NULL
),
ranked AS (SELECT *, LAG(created_at) OVER (PARTITION BY patient_id ORDER BY created_at) AS prev_crt FROM sc_all),
j AS (
  SELECT s.city, s.locality AS clinic,
    TO_CHAR(DATE_TRUNC('week', s.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
    -- new = first-ever SC; rebook = within 14d of prior SC (reschedule / no-show re-book); return = 14+ days later
    CASE WHEN s.prev_crt IS NULL THEN 'new'
         WHEN DATEDIFF(day, s.prev_crt, s.created_at) < 14 THEN 'rebook'
         ELSE 'return' END AS who, s.st, s.prev,
    (s.rsn LIKE '%provider%' OR s.rsn LIKE '%doctor%' OR s.rsn LIKE '%nonbookable%' OR s.rsn LIKE '%hms%' OR s.rsn LIKE '%block%') AS is_clinic_resched
  FROM ranked s
  WHERE s.start_time >= '2026-03-23' AND s.start_time < '2026-06-29'
    AND LOWER(COALESCE(s.locality,'')) <> 'online' AND s.locality IS NOT NULL
)
SELECT city, clinic, wk,
  who,
  COUNT(*) AS total,
  SUM(CASE WHEN st IN ('completed','reconsulted') THEN 1 ELSE 0 END) AS done,
  SUM(CASE WHEN st='missed' THEN 1 ELSE 0 END) AS missed,
  SUM(CASE WHEN st='rescheduled' AND prev<>'missed' AND NOT is_clinic_resched THEN 1 ELSE 0 END) AS resched_patient,
  SUM(CASE WHEN st='rescheduled' AND prev<>'missed' AND is_clinic_resched THEN 1 ELSE 0 END) AS resched_clinic,
  SUM(CASE WHEN st='rescheduled' AND prev='missed' THEN 1 ELSE 0 END) AS resched_noshow,
  SUM(CASE WHEN st='cancelled' THEN 1 ELSE 0 END) AS cancelled,
  SUM(CASE WHEN st IN ('scheduled','confirmed','in_progress','provider_joined') THEN 1 ELSE 0 END) AS scheduled
FROM j
GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;
