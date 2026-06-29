-- LEAD COHORT (forward view): of the leads CREATED in a week, how many booked, by channel,
-- and the booking lag (same week / next week / 2+ weeks later). Indexed by LEAD-CREATION week
-- (created_on) — NOT by booking week. This answers "of this week's leads, how many booked?".
-- Source: production.public.main_source_wise_leads. Offline clinics only (call_location).
-- Note: booked counts a booking at ANY later time (call_booking_ts), so recent lead-weeks read
-- low — those leads are still maturing (haven't had time to book yet).
SELECT loc.city AS city, l.call_location AS clinic,
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
  -- inbound = patient phoned the clinic (organic_l2='PC-Inbound'); the rest are web/form leads
  SUM(CASE WHEN l.organic_l2='PC-Inbound' THEN 1 ELSE 0 END) AS inb_leads,
  SUM(CASE WHEN l.organic_l2='PC-Inbound' AND l.call_booking_ts IS NOT NULL THEN 1 ELSE 0 END) AS inb_booked
FROM production.public.main_source_wise_leads l
JOIN allo_prod.allo_health.locations loc
  ON loc.locality = l.call_location AND loc.deleted_at IS NULL AND loc.is_active = 1
WHERE l.call_location IS NOT NULL AND LOWER(l.call_location) <> 'online'
  AND l.created_on >= '2026-03-23' AND l.created_on < '2026-06-29'
GROUP BY 1,2,3,4 ORDER BY 1,2,3,4
