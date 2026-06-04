-- Lead-age cohort of bookings: of the calls booked in a week, how many came from a lead created
-- THIS week (fresh) vs LAST week (1-wk lag) vs OLDER (2+ wks, backlog). Per clinic, by booking-week.
-- Source: production.public.main_source_wise_leads (created_on = lead time, call_booking_ts = booking time).
SELECT loc.city AS city, l.call_location AS clinic,
  TO_CHAR(DATE_TRUNC('week', l.call_booking_ts),'YYYY-MM-DD') AS wk,
  CASE WHEN DATEDIFF(week, DATE_TRUNC('week', l.created_on), DATE_TRUNC('week', l.call_booking_ts)) <= 0 THEN 'same'
       WHEN DATEDIFF(week, DATE_TRUNC('week', l.created_on), DATE_TRUNC('week', l.call_booking_ts)) = 1 THEN 'last'
       ELSE 'older' END AS age,
  COUNT(*) AS n
FROM production.public.main_source_wise_leads l
JOIN allo_prod.allo_health.locations loc
  ON loc.locality = l.call_location AND loc.deleted_at IS NULL AND loc.is_active = 1
WHERE l.call_booking_ts IS NOT NULL AND l.call_location IS NOT NULL AND LOWER(l.call_location) <> 'online'
  AND l.call_booking_ts >= '2026-03-09' AND l.call_booking_ts < '2026-06-01'
GROUP BY 1,2,3,4 ORDER BY 1,2,3
