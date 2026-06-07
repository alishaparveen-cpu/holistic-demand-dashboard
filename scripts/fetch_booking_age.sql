-- LEAD AGE at booking: how stale the lead was when the Screening Call was booked.
-- age = days between lead.created_at and the appointment being made (appt.created_at),
-- bucketed to match the dashboard's lead-age buckets. Per clinic/week, with outcome split.
WITH sc_all AS (
  SELECT a.id, a.patient_id, a.created_at AS booked_at, a.start_time, LOWER(a.status) AS st,
         LOWER(COALESCE(a.previous_status,'')) AS prev, LOWER(COALESCE(a.reason,'')) AS rsn,
         loc.city, loc.locality
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  WHERE a.deleted_at IS NULL
),
j AS (
  SELECT s.city, s.locality AS clinic,
    TO_CHAR(DATE_TRUNC('week', s.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
    s.st, s.prev,
    (s.rsn LIKE '%provider%' OR s.rsn LIKE '%doctor%' OR s.rsn LIKE '%nonbookable%' OR s.rsn LIKE '%hms%' OR s.rsn LIKE '%block%') AS is_clinic_resched,
    CASE
      WHEN l.id IS NULL OR l.created_at IS NULL THEN 'Unknown'
      WHEN DATEDIFF(day, l.created_at, s.booked_at) < 7 THEN '1 · Same week'
      WHEN DATEDIFF(day, l.created_at, s.booked_at) < 14 THEN '2 · Last week'
      WHEN DATEDIFF(day, l.created_at, s.booked_at) < 28 THEN '3 · 2-4 weeks'
      WHEN DATEDIFF(day, l.created_at, s.booked_at) < 90 THEN '4 · 1-3 months'
      ELSE '5 · 3+ months'
    END AS agebucket
  FROM sc_all s
  LEFT JOIN allo_persons.patient p ON s.patient_id=p.id
  LEFT JOIN allo_persons.lead l ON p.lead_id=l.id
  WHERE s.start_time >= '2026-03-09' AND s.start_time < '2026-06-01'
    AND LOWER(COALESCE(s.locality,'')) <> 'online' AND s.locality IS NOT NULL
)
SELECT city, clinic, wk, agebucket,
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
