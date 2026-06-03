-- Diagnostic headline bookings (allBk): distinct (patient, provider) screening-call OFFLINE
-- bookings by appointment start-week. Matches the demand-tracker sheet's
-- "SC Offline Booked - All Booked During the Week" column (validated: distinct patient-provider,
-- since the sheet sums per-doctor rows). 12 weeks.
WITH sc AS (
  SELECT app.patient_id, app.provider_id, app.start_time, loc.city, loc.locality
  FROM allo_consultations.appointments app
  JOIN allo_health.locations loc ON app.location_id=loc.id AND loc.deleted_at IS NULL
  JOIN allo_consultations.types typ ON app.type_id=typ.id AND typ.name='Screening Call'
  WHERE app.deleted_at IS NULL
    AND LOWER(COALESCE(loc.locality,''))<>'online' AND loc.locality IS NOT NULL
    AND app.start_time >= '2026-03-09' AND app.start_time < '2026-06-01'
)
SELECT city, locality,
  TO_CHAR(DATE_TRUNC('week', start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
  COUNT(DISTINCT patient_id || '-' || provider_id) AS allbk,
  COUNT(DISTINCT CASE WHEN EXTRACT(DOW FROM start_time + INTERVAL '5.5 hours') IN (0,6)
        THEN patient_id || '-' || provider_id END) AS we_allbk
FROM sc GROUP BY 1,2,3 ORDER BY 1,2,3 DESC
