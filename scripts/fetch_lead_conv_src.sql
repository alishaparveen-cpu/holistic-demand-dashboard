-- Lead → Booked → Done by SOURCE (last 4 weeks, network). done = matched SC completed within 14d.
WITH ld AS (
  SELECT DISTINCT RIGHT(phone_no,10) AS ph, DATE(created_at) AS ld_date,
    CASE WHEN LOWER(COALESCE(utm_source,'')) LIKE '%google%' OR LOWER(COALESCE(origin,'')) LIKE '%exotel%' THEN 'Google/Call'
         WHEN LOWER(COALESCE(origin,'')) LIKE '%gmb%' OR LOWER(COALESCE(utm_source,'')) LIKE '%gmb%' OR LOWER(COALESCE(utm_source,'')) LIKE '%googlelisting%' THEN 'GMB'
         WHEN LOWER(COALESCE(origin,'')) LIKE '%practo%' OR LOWER(COALESCE(utm_source,'')) LIKE '%practo%' THEN 'Practo'
         WHEN LOWER(COALESCE(utm_source,'')) LIKE '%fb%' OR LOWER(COALESCE(utm_source,'')) LIKE '%ig%' OR LOWER(COALESCE(utm_source,'')) LIKE '%meta%' THEN 'Meta'
         WHEN LOWER(COALESCE(origin,'')) LIKE '%whatsapp%' THEN 'WhatsApp'
         WHEN LOWER(COALESCE(utm_source,'')) LIKE '%organic%' OR utm_source IS NULL THEN 'Organic/Direct'
         ELSE 'Other' END AS src
  FROM allo_persons.lead
  WHERE created_at >= '2026-05-11' AND created_at < '2026-06-15'
    AND phone_no IS NOT NULL AND LEN(phone_no) >= 10
),
bk AS (
  SELECT RIGHT(p.phone_no,10) AS ph, DATE(a.created_at) AS bdate, LOWER(a.status) AS st
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_persons.patient p ON p.id=a.patient_id
  WHERE a.deleted_at IS NULL AND a.created_at >= '2026-05-11' AND p.phone_no IS NOT NULL
)
SELECT ld.src, COUNT(DISTINCT ld.ph) AS leads,
  COUNT(DISTINCT CASE WHEN b.ph IS NOT NULL THEN ld.ph END) AS booked,
  COUNT(DISTINCT CASE WHEN b.st IN ('completed','reconsulted') THEN ld.ph END) AS done
FROM ld LEFT JOIN bk b ON b.ph=ld.ph AND b.bdate>=ld.ld_date AND b.bdate<=DATEADD(day,14,ld.ld_date)
GROUP BY 1 ORDER BY 2 DESC;
