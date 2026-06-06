-- Clinic Scorecard — appointment-level dispositions per clinic/week, with the reschedule-reason
-- split (patient-requested vs no-show-recycled, via previous_status) and a no-show recovery proxy.
-- Screening Call, offline. new = patient's all-time-first SC (created_at = MIN over full history).
WITH sc_all AS (
  SELECT a.id, a.patient_id, a.created_at, a.start_time, LOWER(a.status) AS st,
         LOWER(COALESCE(a.previous_status,'')) AS prev, loc.city, loc.locality
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  WHERE a.deleted_at IS NULL
),
firsts AS (SELECT patient_id, MIN(created_at) AS first_crt FROM sc_all GROUP BY patient_id)
SELECT s.city, s.locality AS clinic,
  TO_CHAR(DATE_TRUNC('week', s.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
  COUNT(*) AS total,
  SUM(CASE WHEN s.created_at=f.first_crt THEN 1 ELSE 0 END) AS new_bk,
  SUM(CASE WHEN s.created_at<>f.first_crt THEN 1 ELSE 0 END) AS followup_bk,
  SUM(CASE WHEN s.st IN ('completed','reconsulted') THEN 1 ELSE 0 END) AS done,
  SUM(CASE WHEN s.st IN ('completed','reconsulted') AND s.created_at=f.first_crt THEN 1 ELSE 0 END) AS done_new,
  SUM(CASE WHEN s.st IN ('completed','reconsulted') AND s.created_at<>f.first_crt THEN 1 ELSE 0 END) AS done_followup,
  SUM(CASE WHEN s.st='missed' THEN 1 ELSE 0 END) AS missed,
  SUM(CASE WHEN s.st='rescheduled' AND s.prev='missed' THEN 1 ELSE 0 END) AS resched_noshow,
  SUM(CASE WHEN s.st='rescheduled' AND s.prev<>'missed' THEN 1 ELSE 0 END) AS resched_patient,
  -- no-show RECOVERY proxy: appointments now completed whose immediately-prior state was 'missed'
  SUM(CASE WHEN s.st IN ('completed','reconsulted') AND s.prev='missed' THEN 1 ELSE 0 END) AS recovered_done,
  SUM(CASE WHEN s.st='cancelled' THEN 1 ELSE 0 END) AS cancelled,
  SUM(CASE WHEN s.st IN ('scheduled','confirmed','in_progress','provider_joined') THEN 1 ELSE 0 END) AS scheduled
FROM sc_all s JOIN firsts f ON s.patient_id=f.patient_id
WHERE s.start_time >= '2026-03-09' AND s.start_time < '2026-06-01'
  AND LOWER(COALESCE(s.locality,''))<>'online' AND s.locality IS NOT NULL
GROUP BY 1,2,3 ORDER BY 1,2,3
