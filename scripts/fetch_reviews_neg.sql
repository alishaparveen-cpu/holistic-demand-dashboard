-- Recent NEGATIVE Google/GMB reviews (rating <= 3) per clinic, with the actual review text,
-- date, reviewer, and whether the clinic has replied — for the diagnostic's GMB-profile drill.
-- Last ~8 weeks. Build into data_reviews_neg.json keyed "City|Clinic".
SELECT loc.city, loc.locality,
  TO_CHAR(er.review_date,'YYYY-MM-DD') AS dt,
  er.rating,
  COALESCE(er.reviewer_name,'') AS author,
  CASE WHEN COALESCE(er.review_reply,'') <> '' THEN 1 ELSE 0 END AS replied,
  LEFT(REGEXP_REPLACE(COALESCE(er.review,''),'[\r\n\t]+',' '),240) AS txt
FROM allo_health.external_reviews er
JOIN allo_health.locations loc ON loc.id = er.reviewed_for_id AND loc.deleted_at IS NULL
WHERE er.deleted_at IS NULL AND LOWER(er.platform) IN ('google','gmb')
  AND er.rating <= 3 AND er.review_date >= '2026-04-20'
  AND loc.locality IS NOT NULL AND LOWER(loc.locality) <> 'online'
ORDER BY er.review_date DESC
