-- Clinic Scorecard — bookings by source channel per clinic/week (numerator for C2B%; leads
-- denominator comes from data_leads.json in the build). main_source_wise_leads rows are bookings.
SELECT loc.city AS city, l.call_location AS clinic,
  TO_CHAR(DATE_TRUNC('week', l.call_booking_ts),'YYYY-MM-DD') AS wk,
  LOWER(COALESCE(l.source,'(none)')) AS source,
  COUNT(*) AS bookings
FROM production.public.main_source_wise_leads l
JOIN allo_prod.allo_health.locations loc
  ON loc.locality = l.call_location AND loc.deleted_at IS NULL AND loc.is_active = 1
WHERE l.call_booking_ts IS NOT NULL AND l.call_location IS NOT NULL AND LOWER(l.call_location) <> 'online'
  AND l.call_booking_ts >= '2026-03-16' AND l.call_booking_ts < '2026-06-15'
GROUP BY 1,2,3,4 ORDER BY 1,2,3
