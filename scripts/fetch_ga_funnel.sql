-- Google Ads funnel (network, weekly): gclid-attributed leads -> bookings.
-- Clicks come from the GA pull (data_ga_city.json); this provides the leads->book half from Redshift.
WITH ga_leads AS (
  SELECT DISTINCT RIGHT(phone_no,10) AS ph, DATE(created_at) AS ld_date,
    TO_CHAR(DATE_TRUNC('week', created_at),'YYYY-MM-DD') AS wk
  FROM allo_persons.lead
  WHERE created_at >= '2026-03-09' AND created_at < '2026-06-01'
    AND gclid IS NOT NULL AND LEN(gclid)>3 AND phone_no IS NOT NULL AND LEN(phone_no)>=10
),
bk AS (
  SELECT DISTINCT RIGHT(p.phone_no,10) AS ph, DATE(a.created_at) AS bdate
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_persons.patient p ON p.id=a.patient_id
  WHERE a.deleted_at IS NULL AND a.created_at >= '2026-03-09' AND p.phone_no IS NOT NULL
)
SELECT g.wk, COUNT(DISTINCT g.ph) AS leads,
  COUNT(DISTINCT CASE WHEN b.ph IS NOT NULL THEN g.ph END) AS booked
FROM ga_leads g
LEFT JOIN bk b ON b.ph=g.ph AND b.bdate>=g.ld_date AND b.bdate<=DATEADD(day,14,g.ld_date)
GROUP BY 1 ORDER BY 1;
