-- L2C (Lead → Call) funnel, NETWORK weekly. Leads (allo_persons.lead, deduped by phone) → Called
-- (>=1 outbound exotel call within 14d) → Connected (>=1 answered/completed call) → Booked (phone
-- matches a Screening Call appointment within 14d via patient.phone_no). Per-clinic isn't reliable
-- (lead clinic-code present on only ~⅓ of leads), so this is network-level.
WITH ld AS (
  SELECT DISTINCT RIGHT(phone_no,10) AS ph, DATE(created_at) AS ld_date,
    TO_CHAR(DATE_TRUNC('week', created_at),'YYYY-MM-DD') AS wk
  FROM allo_persons.lead
  WHERE phone_no IS NOT NULL AND LEN(phone_no) >= 10
    AND created_at >= '2026-03-09' AND created_at < '2026-06-01'
),
calls AS (
  SELECT RIGHT("to",10) AS ph, DATE(start_time) AS cdate, LOWER(status) AS st
  FROM allo_vendors.exotel_calls
  WHERE direction IN ('outbound','outbound-api') AND deleted_at IS NULL AND start_time >= '2026-03-09'
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
  COUNT(DISTINCT CASE WHEN c.ph IS NOT NULL THEN ld.ph END) AS called,
  COUNT(DISTINCT CASE WHEN c.st='completed' THEN ld.ph END) AS connected,
  COUNT(DISTINCT CASE WHEN b.ph IS NOT NULL THEN ld.ph END) AS booked
FROM ld
LEFT JOIN calls c ON c.ph=ld.ph AND c.cdate>=ld.ld_date AND c.cdate<=DATEADD(day,14,ld.ld_date)
LEFT JOIN bk b ON b.ph=ld.ph AND b.bdate>=ld.ld_date AND b.bdate<=DATEADD(day,14,ld.ld_date)
GROUP BY 1 ORDER BY 1;
