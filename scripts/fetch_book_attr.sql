-- BOOKING ATTRIBUTION (network): of the bookings made in a week, how OLD was the lead that drove
-- each one (same week / 1 wk back / 2 wk back / 3+ wk back) and from which channel. Indexed by the
-- BOOKING week (call_booking_ts). All digital leads, no clinic filter (call_location is booking-only).
SELECT
  TO_CHAR(DATE_TRUNC('week', l.call_booking_ts),'YYYY-MM-DD') AS bk_wk,
  CASE WHEN l.source='Google' THEN 'google_ad'
       WHEN l.source='Organic' AND l.organic_l2 IN ('Google Listing','PC-Inbound') THEN 'gmb'
       WHEN l.source='Organic' THEN 'organic'
       WHEN l.source IN ('Fb','Instagram') THEN 'fb'
       WHEN l.source='Justdial' THEN 'justdial'
       ELSE 'others' END AS chan,
  LEAST(GREATEST(DATEDIFF(week, DATE_TRUNC('week',l.created_on), DATE_TRUNC('week',l.call_booking_ts)),0),4) AS age,
  COUNT(*) AS n
FROM production.public.main_source_wise_leads l
WHERE l.call_booking_ts >= '2026-03-16' AND l.call_booking_ts < '2026-06-15'
  AND l.created_on IS NOT NULL
GROUP BY 1,2,3 ORDER BY 1,2,3
