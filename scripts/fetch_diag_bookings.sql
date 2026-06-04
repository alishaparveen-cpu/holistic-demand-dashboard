-- Diagnostic headline bookings (allBk) + its new/repeat + weekend split, all on ONE basis so
-- they reconcile: distinct (patient, provider) screening-call OFFLINE bookings by appointment
-- start-week. allBk = new_bk + repeat_bk. Matches the demand-tracker sheet's "SC Offline Booked
-- - All Booked During the Week" (validated). "new" = the patient's ALL-TIME first SC visit
-- (computed across full history, incl. online, so early weeks aren't over-counted). 12 weeks.
WITH sc_all AS (
  SELECT app.id, app.patient_id, app.provider_id, app.created_at, app.start_time, app.status, loc.city, loc.locality
  FROM allo_consultations.appointments app
  JOIN allo_health.locations loc ON app.location_id=loc.id AND loc.deleted_at IS NULL
  JOIN allo_consultations.types typ ON app.type_id=typ.id AND typ.name='Screening Call'
  WHERE app.deleted_at IS NULL
),
firsts AS (SELECT patient_id, MIN(created_at) AS first_crt FROM sc_all GROUP BY patient_id),
flagged AS (
  SELECT s.city, s.locality,
    TO_CHAR(DATE_TRUNC('week', s.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
    s.patient_id, s.provider_id,
    (s.created_at = f.first_crt) AS is_new,
    (EXTRACT(DOW FROM s.start_time + INTERVAL '5.5 hours') IN (0,6)) AS is_we,
    (LOWER(s.status) IN ('completed','reconsulted')) AS is_done
  FROM sc_all s JOIN firsts f ON s.patient_id = f.patient_id
  WHERE s.start_time >= '2026-03-09' AND s.start_time < '2026-06-01'
    AND LOWER(COALESCE(s.locality,'')) <> 'online' AND s.locality IS NOT NULL
),
pairs AS (
  SELECT city, locality, wk, patient_id, provider_id,
    BOOL_OR(is_new) AS pair_new, BOOL_OR(is_we) AS pair_we, BOOL_OR(is_done) AS pair_done
  FROM flagged GROUP BY 1,2,3,4,5
)
SELECT city, locality, wk,
  COUNT(*) AS allbk,
  SUM(CASE WHEN pair_we THEN 1 ELSE 0 END) AS we_allbk,
  SUM(CASE WHEN pair_new THEN 1 ELSE 0 END) AS new_bk,
  SUM(CASE WHEN NOT pair_new THEN 1 ELSE 0 END) AS repeat_bk,
  SUM(CASE WHEN pair_done THEN 1 ELSE 0 END) AS done_bk
FROM pairs GROUP BY 1,2,3 ORDER BY 1,2,3 DESC
