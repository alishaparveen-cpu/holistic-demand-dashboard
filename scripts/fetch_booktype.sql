-- Booking-type decomposition: new (first-EVER visit) vs repeat (returning) screening-call
-- appointments, per clinic per appointment-week. "New" is determined by each patient's
-- ALL-TIME first SC appointment (created_at), computed across full history — NOT windowed —
-- so early weeks in the reporting window are not over-counted as "new" (left-censoring fix).
-- new + repeat = total SC appointments that week (gross, every status).
WITH sc_all AS (
  SELECT app.id, app.patient_id, app.created_at, app.start_time, app.status, loc.city, loc.locality
  FROM allo_consultations.appointments app
  JOIN allo_health.locations loc ON app.location_id=loc.id AND loc.deleted_at IS NULL
  JOIN allo_consultations.types typ ON app.type_id=typ.id AND typ.name='Screening Call'
  WHERE app.deleted_at IS NULL
),
firsts AS (SELECT patient_id, MIN(created_at) AS first_crt FROM sc_all GROUP BY patient_id)
SELECT s.city, s.locality,
  TO_CHAR(DATE_TRUNC('week', s.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
  SUM(CASE WHEN s.created_at = f.first_crt THEN 1 ELSE 0 END) AS new_bk,
  SUM(CASE WHEN s.created_at > f.first_crt THEN 1 ELSE 0 END) AS repeat_bk,
  SUM(CASE WHEN LOWER(s.status)='cancelled' THEN 1 ELSE 0 END) AS cancelled,
  COUNT(*) AS total
FROM sc_all s JOIN firsts f ON s.patient_id = f.patient_id
WHERE s.start_time >= '2026-03-23' AND s.start_time < '2026-06-29'
  AND LOWER(COALESCE(s.locality,'')) <> 'online' AND s.locality IS NOT NULL
GROUP BY 1,2,3 ORDER BY 1,2,3 DESC
