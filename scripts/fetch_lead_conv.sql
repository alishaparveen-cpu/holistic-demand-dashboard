-- Lead -> conversion by HOW we engaged the lead (contact mode), network weekly.
-- Mode priority: inbound call > outbound call > WhatsApp > website self-serve > other.
-- booked = phone matched a Screening Call within 14d. Contact = exotel call within 14d.
WITH ld AS (
  SELECT DISTINCT RIGHT(phone_no,10) AS ph, DATE(created_at) AS ld_date,
    TO_CHAR(DATE_TRUNC('week',created_at),'YYYY-MM-DD') AS wk,
    LOWER(COALESCE(origin,'')) AS orig, user_flow
  FROM allo_persons.lead
  WHERE created_at >= '2026-03-09' AND created_at < '2026-06-01'
    AND phone_no IS NOT NULL AND LEN(phone_no) >= 10
),
calls AS (
  SELECT RIGHT(CASE WHEN direction='inbound' THEN "from" ELSE "to" END,10) AS ph,
    CASE WHEN direction='inbound' THEN 'in' ELSE 'out' END AS dir, DATE(start_time) AS cdate
  FROM allo_vendors.exotel_calls WHERE deleted_at IS NULL AND start_time >= '2026-03-09'
),
bk AS (
  SELECT DISTINCT RIGHT(p.phone_no,10) AS ph, DATE(a.created_at) AS bdate
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_persons.patient p ON p.id=a.patient_id
  WHERE a.deleted_at IS NULL AND a.created_at >= '2026-03-09' AND p.phone_no IS NOT NULL
),
j AS (
  SELECT ld.ph, ld.wk,
    MAX(CASE WHEN c.dir='in' THEN 1 ELSE 0 END) AS has_in,
    MAX(CASE WHEN c.dir='out' THEN 1 ELSE 0 END) AS has_out,
    MAX(CASE WHEN ld.orig LIKE '%whatsapp%' THEN 1 ELSE 0 END) AS is_wa,
    MAX(CASE WHEN ld.user_flow IS NOT NULL OR ld.orig LIKE '%allohealth%' OR ld.orig LIKE '%http%' OR ld.orig LIKE '%allo health%' THEN 1 ELSE 0 END) AS is_web,
    MAX(CASE WHEN b.ph IS NOT NULL THEN 1 ELSE 0 END) AS booked
  FROM ld
  LEFT JOIN calls c ON c.ph=ld.ph AND c.cdate>=ld.ld_date AND c.cdate<=DATEADD(day,14,ld.ld_date)
  LEFT JOIN bk b ON b.ph=ld.ph AND b.bdate>=ld.ld_date AND b.bdate<=DATEADD(day,14,ld.ld_date)
  GROUP BY ld.ph, ld.wk
)
SELECT wk,
  CASE WHEN has_in=1 THEN '1 Inbound call' WHEN has_out=1 THEN '2 Outbound call'
       WHEN is_wa=1 THEN '3 WhatsApp' WHEN is_web=1 THEN '4 Website self-serve'
       ELSE '5 Other' END AS mode,
  COUNT(*) AS leads, SUM(booked) AS booked
FROM j GROUP BY 1,2 ORDER BY 1,2;
