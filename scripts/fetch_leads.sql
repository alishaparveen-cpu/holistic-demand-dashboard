-- Per clinic/week leads from production.public.main_source_wise_leads (Redshift,
-- hourly QS2 job). Buckets:
--   google_ad = paid Google Ads (source='Google')
--   gmb       = GMB profile: listing clicks + inbound calls (Organic / Google Listing + PC-Inbound)
--   organic   = other organic / web / walk-in
--   fb        = Meta (Fb + Instagram) · justdial · others = everything else
-- Practo intentionally excluded (external feed). Offline only (call_location).
SELECT loc.city AS city, l.call_location AS clinic,
  TO_CHAR(DATE(l.week)::date - 6, 'YYYY-MM-DD') AS wk_mon,
  SUM(CASE WHEN l.source='Google' THEN 1 ELSE 0 END) AS google_ad,
  SUM(CASE WHEN l.source='Organic' AND l.organic_l2 IN ('Google Listing','PC-Inbound') THEN 1 ELSE 0 END) AS gmb,
  SUM(CASE WHEN l.source='Organic' AND COALESCE(l.organic_l2,'') NOT IN ('Google Listing','PC-Inbound') THEN 1 ELSE 0 END) AS organic,
  SUM(CASE WHEN l.source IN ('Fb','Instagram') THEN 1 ELSE 0 END) AS fb,
  SUM(CASE WHEN l.source='Justdial' THEN 1 ELSE 0 END) AS justdial,
  SUM(CASE WHEN l.source NOT IN ('Google','Organic','Fb','Instagram','Justdial') THEN 1 ELSE 0 END) AS others,
  COUNT(*) AS total
FROM production.public.main_source_wise_leads l
JOIN allo_prod.allo_health.locations loc
  ON loc.locality = l.call_location AND loc.deleted_at IS NULL AND loc.is_active = 1
WHERE l.call_location IS NOT NULL AND LOWER(l.call_location) <> 'online'
  AND l.week >= '2026-03-09' AND l.week < '2026-06-02'
GROUP BY 1,2,3 ORDER BY 1,2,3 DESC
