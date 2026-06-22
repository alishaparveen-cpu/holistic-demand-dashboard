-- Diagnostic availability (active doctor-days, realized): distinct (provider, date) where the
-- provider had at least one BOOKABLE, NON-SHRUNK screening-call roster slot that day. A slot is
-- "shrunk" when an appointment_blocks row (is_bookable=false) overlaps it. weekend = those on
-- Sat/Sun. This is the accurate Redshift measure (scheduled-vs-realized shrinkage). 12 weeks.
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
    AND rs.start_time >= '2026-03-23' AND rs.start_time < '2026-06-22'
    AND LOWER(COALESCE(loc.locality,''))<>'online' AND loc.locality IS NOT NULL
  GROUP BY 1,2,3,4,5,6, rs.start_time
),
pd AS (
  SELECT city, locality, wk, provider_id, dt, dow, BOOL_OR(NOT is_shrunk) AS day_active
  FROM slots GROUP BY 1,2,3,4,5,6
)
SELECT city, locality, wk,
  COUNT(DISTINCT CASE WHEN day_active THEN provider_id||'-'||dt END) AS active_days,
  COUNT(DISTINCT CASE WHEN day_active AND dow IN (0,6) THEN provider_id||'-'||dt END) AS we_days
FROM pd GROUP BY 1,2,3 ORDER BY 1,2,3 DESC
