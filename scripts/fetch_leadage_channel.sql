-- Lead age at booking, split by CHANNEL, per clinic/week. Lets us see whether (e.g.) GMB leads
-- book same-week while organic leads are older. Channel mapping matches fetch_leads.sql.
-- Source: main_source_wise_leads (created_on = lead, call_booking_ts = booking). Practo is a
-- separate external feed and not in this table, so it's excluded from the age split.
SELECT loc.city AS city, l.call_location AS clinic,
  TO_CHAR(DATE_TRUNC('week', l.call_booking_ts),'YYYY-MM-DD') AS wk,
  CASE WHEN l.source='Google' THEN 'google_ad'
       WHEN l.source='Organic' AND l.organic_l2 IN ('Google Listing','PC-Inbound') THEN 'gmb'
       WHEN l.source='Organic' THEN 'organic'
       WHEN l.source IN ('Fb','Instagram') THEN 'fb'
       WHEN l.source='Justdial' THEN 'justdial'
       ELSE 'others' END AS channel,
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
GROUP BY 1,2,3,4,5 ORDER BY 1,2,3,4,5;
