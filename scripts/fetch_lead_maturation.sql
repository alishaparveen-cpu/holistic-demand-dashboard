-- Lead-cohort maturation (Google/GMB/Organic universe — the channels with booking-timing).
-- For leads CREATED each week, count bookings at lag 0 (same week), 1, 2, 3, 4+ weeks later.
-- Numerator only; denominator (total non-Practo inbound leads/week) comes from data_leads.json in the
-- build. Source: production.public.main_source_wise_leads (1 row per booked lead, with created_on & booking ts).
WITH leads AS (
  SELECT loc.city AS city, l.call_location AS clinic,
    DATE_TRUNC('week', l.created_on) AS cohort_wk,
    DATEDIFF(week, DATE_TRUNC('week', l.created_on), DATE_TRUNC('week', l.call_booking_ts)) AS lag_wk
  FROM production.public.main_source_wise_leads l
  JOIN allo_prod.allo_health.locations loc
    ON loc.locality = l.call_location AND loc.deleted_at IS NULL AND loc.is_active = 1
  WHERE l.created_on >= '2026-03-23' AND l.created_on < '2026-06-22'
    AND l.call_booking_ts IS NOT NULL
    AND l.call_location IS NOT NULL AND LOWER(l.call_location) <> 'online'
)
SELECT city, clinic, TO_CHAR(cohort_wk,'YYYY-MM-DD') AS cohort,
  SUM(CASE WHEN lag_wk = 0 THEN 1 ELSE 0 END) AS b0,
  SUM(CASE WHEN lag_wk = 1 THEN 1 ELSE 0 END) AS b1,
  SUM(CASE WHEN lag_wk = 2 THEN 1 ELSE 0 END) AS b2,
  SUM(CASE WHEN lag_wk = 3 THEN 1 ELSE 0 END) AS b3,
  SUM(CASE WHEN lag_wk >= 4 THEN 1 ELSE 0 END) AS b4p
FROM leads GROUP BY 1,2,3 ORDER BY 1,2,3
