-- Per clinic/week leads from production.public.main_source_wise_leads (Redshift,
-- hourly QS2 job). Buckets:
--   google_ad  = paid Google Ads (source='Google')
--   gmb        = GMB profile: listing clicks + inbound calls + GMB→WhatsApp (utm_source=gmb,utm_medium=whatsapp)
--   organic    = other organic / web / walk-in (excl. GMB-WA, Practo CRM, outbound WA re-engagement)
--   fb         = Meta (Fb + Instagram) · justdial · others = everything else (excl. Practo CRM)
--   practo_crm = Practo leads entering via retool or Practo app (utm_source=practo in allo_persons.lead)
--                NOT in the external Practo sheet — that lives in data_practo_leads.json
--   outbound_wa= CRM-initiated WhatsApp re-engagement to existing leads (excluded from new demand count)
-- Practo external feed intentionally excluded here (separate in data_practo_leads.json).
-- Offline only (call_location).
WITH lead_utm AS (
  SELECT
    RIGHT(REGEXP_REPLACE(phone_no,'[^0-9]',''),10) AS phone10,
    DATE_TRUNC('week', created_at + INTERVAL '5 hours 30 minutes')::date AS wk_mon,
    MAX(utm_source)   AS utm_source,
    MAX(utm_medium)   AS utm_medium,
    MAX(utm_campaign) AS utm_campaign
  FROM allo_persons.lead
  WHERE created_at >= '2026-03-01'
  GROUP BY 1, 2
)
SELECT loc.city AS city, l.call_location AS clinic,
  TO_CHAR(DATE(l.week)::date - 6, 'YYYY-MM-DD') AS wk_mon,
  SUM(CASE WHEN l.source='Google' THEN 1 ELSE 0 END) AS google_ad,
  SUM(CASE WHEN (l.source='Organic' AND l.organic_l2 IN ('Google Listing','PC-Inbound'))
               OR (lu.utm_source='gmb' AND lu.utm_medium='whatsapp')
           THEN 1 ELSE 0 END) AS gmb,
  SUM(CASE WHEN l.source='Organic'
               AND COALESCE(l.organic_l2,'') NOT IN ('Google Listing','PC-Inbound')
               AND NOT (lu.utm_source='gmb' AND lu.utm_medium='whatsapp')
               AND NOT (lu.utm_source='practo')
               AND NOT (lu.utm_medium='whatsapp' AND lu.utm_campaign='outbound')
           THEN 1 ELSE 0 END) AS organic,
  SUM(CASE WHEN l.source IN ('Fb','Instagram') THEN 1 ELSE 0 END) AS fb,
  SUM(CASE WHEN l.source='Justdial' THEN 1 ELSE 0 END) AS justdial,
  SUM(CASE WHEN l.source NOT IN ('Google','Organic','Fb','Instagram','Justdial')
               AND NOT (lu.utm_source='practo')
           THEN 1 ELSE 0 END) AS others,
  SUM(CASE WHEN lu.utm_source='practo' THEN 1 ELSE 0 END) AS practo_crm,
  SUM(CASE WHEN lu.utm_medium='whatsapp' AND lu.utm_campaign='outbound' THEN 1 ELSE 0 END) AS outbound_wa,
  COUNT(*) AS total
FROM production.public.main_source_wise_leads l
JOIN allo_prod.allo_health.locations loc
  ON loc.locality = l.call_location AND loc.deleted_at IS NULL AND loc.is_active = 1
LEFT JOIN lead_utm lu
  ON lu.phone10 = RIGHT(REGEXP_REPLACE(l.phone_no1,'[^0-9]',''),10)
  AND lu.wk_mon = DATE_TRUNC('week', l.created_on_date)::date
WHERE l.call_location IS NOT NULL AND LOWER(l.call_location) <> 'online'
  AND l.week >= '2026-03-16' AND l.week < '2026-06-22'
GROUP BY 1,2,3 ORDER BY 1,2,3 DESC
