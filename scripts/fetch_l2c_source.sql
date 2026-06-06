-- L2C by lead SOURCE (last 4 complete weeks aggregated): leads -> reached(any) -> connected -> booked.
WITH ld AS (
  SELECT DISTINCT RIGHT(phone_no,10) AS ph, DATE(created_at) AS ld_date,
    CASE WHEN utm_source='google' THEN 'Google Ads'
         WHEN utm_source IN ('gmb','googlelisting') THEN 'GMB'
         WHEN utm_source IN ('fb','ig') THEN 'Meta / FB'
         WHEN utm_source='practo' THEN 'Practo'
         WHEN utm_source='organic' THEN 'Organic'
         ELSE 'Other' END AS src
  FROM allo_persons.lead
  WHERE phone_no IS NOT NULL AND LEN(phone_no)>=10 AND created_at>='2026-04-27' AND created_at<'2026-05-25'),
calls AS (SELECT RIGHT(CASE WHEN direction='inbound' THEN "from" ELSE "to" END,10) AS ph, DATE(start_time) cdate, LOWER(status) st
  FROM allo_vendors.exotel_calls WHERE deleted_at IS NULL AND start_time>='2026-04-27'),
bk AS (SELECT DISTINCT RIGHT(p.phone_no,10) AS ph, DATE(a.created_at) bdate FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_persons.patient p ON p.id=a.patient_id WHERE a.deleted_at IS NULL AND a.created_at>='2026-04-27' AND p.phone_no IS NOT NULL)
SELECT ld.src, COUNT(DISTINCT ld.ph) leads,
  COUNT(DISTINCT CASE WHEN c.ph IS NOT NULL THEN ld.ph END) reached,
  COUNT(DISTINCT CASE WHEN c.st='completed' THEN ld.ph END) connected,
  COUNT(DISTINCT CASE WHEN b.ph IS NOT NULL THEN ld.ph END) booked
FROM ld LEFT JOIN calls c ON c.ph=ld.ph AND c.cdate>=ld.ld_date AND c.cdate<=DATEADD(day,14,ld.ld_date)
LEFT JOIN bk b ON b.ph=ld.ph AND b.bdate>=ld.ld_date AND b.bdate<=DATEADD(day,14,ld.ld_date)
GROUP BY 1 ORDER BY leads DESC;
