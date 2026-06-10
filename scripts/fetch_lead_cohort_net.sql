-- NETWORK lead cohort (true funnel) — ALL digital leads, no clinic-location filter.
-- call_location is only populated when a lead books, so the per-clinic build (with the
-- locations JOIN) only sees booked leads (≈100% conversion). This network query keeps every
-- lead, so booked ÷ leads is the real lead→book conversion. By LEAD-CREATION week & channel,
-- with the inbound (PC-Inbound = phoned us) split and booking lag.
SELECT
  TO_CHAR(DATE_TRUNC('week', l.created_on),'YYYY-MM-DD') AS lead_wk,
  CASE WHEN l.source='Google' THEN 'google_ad'
       WHEN l.source='Organic' AND l.organic_l2 IN ('Google Listing','PC-Inbound') THEN 'gmb'
       WHEN l.source='Organic' THEN 'organic'
       WHEN l.source IN ('Fb','Instagram') THEN 'fb'
       WHEN l.source='Justdial' THEN 'justdial'
       ELSE 'others' END AS chan,
  COUNT(*) AS leads,
  COUNT(l.call_booking_ts) AS booked,
  SUM(CASE WHEN l.call_booking_ts IS NOT NULL AND DATEDIFF(week, DATE_TRUNC('week',l.created_on), DATE_TRUNC('week',l.call_booking_ts))<=0 THEN 1 ELSE 0 END) AS same,
  SUM(CASE WHEN l.call_booking_ts IS NOT NULL AND DATEDIFF(week, DATE_TRUNC('week',l.created_on), DATE_TRUNC('week',l.call_booking_ts))=1 THEN 1 ELSE 0 END) AS nextw,
  SUM(CASE WHEN l.call_booking_ts IS NOT NULL AND DATEDIFF(week, DATE_TRUNC('week',l.created_on), DATE_TRUNC('week',l.call_booking_ts))>=2 THEN 1 ELSE 0 END) AS later,
  SUM(CASE WHEN l.organic_l2='PC-Inbound' THEN 1 ELSE 0 END) AS inb_leads,
  SUM(CASE WHEN l.organic_l2='PC-Inbound' AND l.call_booking_ts IS NOT NULL THEN 1 ELSE 0 END) AS inb_booked
FROM production.public.main_source_wise_leads l
WHERE l.created_on >= '2026-03-16' AND l.created_on < '2026-06-08'
GROUP BY 1,2 ORDER BY 1,2
