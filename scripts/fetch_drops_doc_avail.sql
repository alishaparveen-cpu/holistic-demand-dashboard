-- Per-DOCTOR active days (realized, post-shrinkage) — same roster logic as the clinic-level
-- diagnostic availability, but grouped by provider so the Diagnostic View can show availability
-- at doctor level. active_days = distinct days the provider had a bookable, non-shrunk screening
-- roster slot; we_days = those on Sat/Sun. 12 weeks, offline clinics only.
WITH slots AS (
  SELECT loc.city, loc.locality,
         TO_CHAR(DATE_TRUNC('week', rs.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
         rs.provider_id,
         (rs.start_time + INTERVAL '5.5 hours')::date AS dt,
         EXTRACT(DOW FROM rs.start_time + INTERVAL '5.5 hours') AS dow,
         BOOL_OR(ab.id IS NOT NULL) AS is_shrunk
  FROM allo_consultations.roster_slots rs
  JOIN allo_health.locations loc ON loc.id=rs.location_id AND loc.deleted_at IS NULL
  LEFT JOIN allo_consultations.appointment_blocks ab
    ON ab.provider_id=rs.provider_id AND ab.is_bookable=false AND ab.deleted_at IS NULL
   AND ab.start_time < rs.end_time AND ab.end_time > rs.start_time
  WHERE rs.type_id='cd02525c-1528-4047-a12c-1ad526c28c9a' AND rs.available_for_booking=1
    AND rs.start_time >= '2026-03-16' AND rs.start_time < '2026-06-15'
    AND LOWER(COALESCE(loc.locality,''))<>'online' AND loc.locality IS NOT NULL
  GROUP BY 1,2,3,4,5,6, rs.start_time
),
pd AS (
  SELECT city, locality, wk, provider_id, dt, dow, BOOL_OR(NOT is_shrunk) AS day_active
  FROM slots GROUP BY 1,2,3,4,5,6
)
SELECT pd.city, pd.locality, COALESCE(NULLIF(TRIM(pr.name),''),'(unassigned)') AS doctor, pd.wk,
  COUNT(DISTINCT CASE WHEN day_active THEN pd.dt END) AS active_days,
  COUNT(DISTINCT CASE WHEN day_active AND dow IN (0,6) THEN pd.dt END) AS we_days
FROM pd LEFT JOIN allo_persons.providers pr ON pr.id=pd.provider_id
GROUP BY 1,2,3,4 ORDER BY 1,2,3,4
