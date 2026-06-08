-- Channel → Booked → full disposition (done/no-show/rescheduled/cancelled/pending) + recovery. Last 4 weeks.
WITH ld AS (
  SELECT DISTINCT RIGHT(phone_no,10) AS ph, DATE(created_at) AS ld_date,
    CASE WHEN LOWER(COALESCE(utm_source,'')) LIKE '%google%' OR LOWER(COALESCE(origin,'')) LIKE '%exotel%' THEN 'Google/Call'
         WHEN LOWER(COALESCE(origin,'')) LIKE '%gmb%' OR LOWER(COALESCE(utm_source,'')) LIKE '%gmb%' OR LOWER(COALESCE(utm_source,'')) LIKE '%googlelisting%' THEN 'GMB'
         WHEN LOWER(COALESCE(origin,'')) LIKE '%practo%' OR LOWER(COALESCE(utm_source,'')) LIKE '%practo%' THEN 'Practo'
         WHEN LOWER(COALESCE(utm_source,'')) LIKE '%fb%' OR LOWER(COALESCE(utm_source,'')) LIKE '%ig%' OR LOWER(COALESCE(utm_source,'')) LIKE '%meta%' THEN 'Meta'
         WHEN LOWER(COALESCE(origin,'')) LIKE '%whatsapp%' THEN 'WhatsApp'
         WHEN LOWER(COALESCE(utm_source,'')) LIKE '%organic%' OR utm_source IS NULL THEN 'Organic/Direct'
         ELSE 'Other' END AS src
  FROM allo_persons.lead WHERE created_at >= '2026-05-11' AND created_at < '2026-06-08' AND phone_no IS NOT NULL AND LEN(phone_no)>=10
),
bk AS (
  SELECT RIGHT(p.phone_no,10) AS ph, DATE(a.created_at) AS bdate, LOWER(a.status) AS st, LOWER(COALESCE(a.previous_status,'')) AS prev
  FROM allo_consultations.appointments a JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_persons.patient p ON p.id=a.patient_id
  WHERE a.deleted_at IS NULL AND a.created_at >= '2026-05-11' AND p.phone_no IS NOT NULL
),
agg AS (
  SELECT ld.src, ld.ph,
    MAX(CASE WHEN b.st IN ('completed','reconsulted') THEN 1 ELSE 0 END) AS done,
    MAX(CASE WHEN b.st='missed' THEN 1 ELSE 0 END) AS missed,
    MAX(CASE WHEN b.st='rescheduled' THEN 1 ELSE 0 END) AS resched,
    MAX(CASE WHEN b.st='cancelled' THEN 1 ELSE 0 END) AS cancelled,
    MAX(CASE WHEN b.st IN ('scheduled','confirmed','in_progress','provider_joined') THEN 1 ELSE 0 END) AS pend,
    MAX(CASE WHEN b.st IN ('completed','reconsulted') AND b.prev='missed' THEN 1 ELSE 0 END) AS recovered
  FROM ld JOIN bk b ON b.ph=ld.ph AND b.bdate>=ld.ld_date AND b.bdate<=DATEADD(day,14,ld.ld_date)
  GROUP BY 1,2
)
SELECT src, COUNT(*) booked, SUM(done) done,
  SUM(CASE WHEN done=0 AND missed=1 THEN 1 ELSE 0 END) noshow,
  SUM(CASE WHEN done=0 AND missed=0 AND resched=1 THEN 1 ELSE 0 END) resched,
  SUM(CASE WHEN done=0 AND missed=0 AND resched=0 AND cancelled=1 THEN 1 ELSE 0 END) cancelled,
  SUM(CASE WHEN done=0 AND missed=0 AND resched=0 AND cancelled=0 AND pend=1 THEN 1 ELSE 0 END) pending,
  SUM(recovered) recovered
FROM agg GROUP BY 1 ORDER BY 2 DESC;
