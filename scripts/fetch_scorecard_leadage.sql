-- Clinic Scorecard — new bookings by FINE lead-age bucket (per clinic, per booking week):
-- of the calls booked in a week, how old was the lead — same wk / last wk / 2-4 wk / 1-3 mo / 3+ mo.
-- Source: production.public.main_source_wise_leads (created_on = lead, call_booking_ts = booking).
SELECT loc.city AS city, l.call_location AS clinic,
  TO_CHAR(DATE_TRUNC('week', l.call_booking_ts),'YYYY-MM-DD') AS wk,
  CASE
    WHEN DATEDIFF(day, l.created_on, l.call_booking_ts) <= 6  THEN 'b0_same'
    WHEN DATEDIFF(day, l.created_on, l.call_booking_ts) <= 14 THEN 'b1_lastwk'
    WHEN DATEDIFF(day, l.created_on, l.call_booking_ts) <= 28 THEN 'b2_2to4wk'
    WHEN DATEDIFF(day, l.created_on, l.call_booking_ts) <= 90 THEN 'b3_1to3mo'
    ELSE 'b4_3moplus' END AS age_bucket,
  COUNT(*) AS n
FROM production.public.main_source_wise_leads l
JOIN allo_prod.allo_health.locations loc
  ON loc.locality = l.call_location AND loc.deleted_at IS NULL AND loc.is_active = 1
WHERE l.call_booking_ts IS NOT NULL AND l.call_location IS NOT NULL AND LOWER(l.call_location) <> 'online'
  AND l.call_booking_ts >= '2026-03-16' AND l.call_booking_ts < '2026-06-08'
GROUP BY 1,2,3,4 ORDER BY 1,2,3
