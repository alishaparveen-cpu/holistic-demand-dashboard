-- L2C funnel NETWORK weekly, with INBOUND vs OUTBOUND split. Leads (allo_persons.lead, deduped
-- phone) → Reached (any call in/out within 14d) → Connected (any answered call) → Booked (SC appt
-- within 14d). Split: out_* = team dialled out; in_* = lead called in.
WITH ld AS (
  SELECT DISTINCT RIGHT(phone_no,10) AS ph, DATE(created_at) AS ld_date,
    TO_CHAR(DATE_TRUNC('week', created_at),'YYYY-MM-DD') AS wk
  FROM allo_persons.lead
  WHERE phone_no IS NOT NULL AND LEN(phone_no) >= 10
    AND created_at >= '2026-03-09' AND created_at < '2026-06-01'
),
calls AS (
  SELECT RIGHT(CASE WHEN direction='inbound' THEN "from" ELSE "to" END,10) AS ph,
    CASE WHEN direction='inbound' THEN 'in' ELSE 'out' END AS dir,
    DATE(start_time) AS cdate, LOWER(status) AS st
  FROM allo_vendors.exotel_calls WHERE deleted_at IS NULL AND start_time >= '2026-03-09'
),
bk AS (
  SELECT DISTINCT RIGHT(p.phone_no,10) AS ph, DATE(a.created_at) AS bdate
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_persons.patient p ON p.id=a.patient_id
  WHERE a.deleted_at IS NULL AND a.created_at >= '2026-03-09' AND p.phone_no IS NOT NULL
)
SELECT ld.wk,
  COUNT(DISTINCT ld.ph) AS leads,
  COUNT(DISTINCT CASE WHEN c.dir='out' THEN ld.ph END) AS out_reached,
  COUNT(DISTINCT CASE WHEN c.dir='out' AND c.st='completed' THEN ld.ph END) AS out_conn,
  COUNT(DISTINCT CASE WHEN c.dir='in' THEN ld.ph END) AS in_reached,
  COUNT(DISTINCT CASE WHEN c.dir='in' AND c.st='completed' THEN ld.ph END) AS in_conn,
  COUNT(DISTINCT CASE WHEN c.ph IS NOT NULL THEN ld.ph END) AS any_reached,
  COUNT(DISTINCT CASE WHEN c.st='completed' THEN ld.ph END) AS any_conn,
  COUNT(DISTINCT CASE WHEN b.ph IS NOT NULL THEN ld.ph END) AS booked
FROM ld
LEFT JOIN calls c ON c.ph=ld.ph AND c.cdate>=ld.ld_date AND c.cdate<=DATEADD(day,14,ld.ld_date)
LEFT JOIN bk b ON b.ph=ld.ph AND b.bdate>=ld.ld_date AND b.bdate<=DATEADD(day,14,ld.ld_date)
GROUP BY 1 ORDER BY 1;
