SELECT loc.city, loc.locality,
  TO_CHAR(DATE_TRUNC('week', er.review_date + INTERVAL '5.5 hours')::date,'YYYY-MM-DD') wk_mon,
  COUNT(*) n, ROUND(AVG(er.rating::float),2) avg_rating,
  SUM(CASE WHEN er.rating<=3 THEN 1 ELSE 0 END) neg
FROM allo_health.external_reviews er
JOIN allo_health.locations loc ON loc.id = er.reviewed_for_id AND loc.deleted_at IS NULL
WHERE er.deleted_at IS NULL AND LOWER(er.platform) IN ('google','gmb')
  AND er.review_date >= '2026-03-16' AND er.review_date < '2026-06-15'
  AND loc.locality IS NOT NULL AND LOWER(loc.locality)<>'online'
GROUP BY 1,2,3 ORDER BY 1,2,3 DESC
