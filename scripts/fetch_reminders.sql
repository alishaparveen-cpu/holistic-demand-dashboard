-- Clinic Scorecard Phase-2 — WhatsApp appointment-reminder funnel per clinic/week.
-- For each Screening-Call appointment, did a reminder template go out (reference_id = appointment.id),
-- and was it delivered / read. Split out no-shows specifically to test the "no reminder sent" hypothesis.
-- Reminder = whatsapp.reference_entity='appointment' AND template ILIKE '%reminder%'.
WITH sc AS (
  SELECT a.id, LOWER(a.status) AS st, a.start_time, loc.city, loc.locality
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  WHERE a.deleted_at IS NULL
    AND a.start_time >= '2026-03-09' AND a.start_time < '2026-06-01'
    AND LOWER(COALESCE(loc.locality,'')) <> 'online' AND loc.locality IS NOT NULL
),
rem AS (
  SELECT w.reference_id AS appt_id,
    MAX(1) AS sent,
    MAX(CASE WHEN w.delivery_time IS NOT NULL OR w.status IN ('delivered','read') THEN 1 ELSE 0 END) AS delivered,
    MAX(CASE WHEN w.read_time IS NOT NULL OR w.status = 'read' THEN 1 ELSE 0 END) AS rd
  FROM allo_vendors.whatsapp w
  WHERE w.reference_entity = 'appointment' AND w.deleted_at IS NULL
    AND w.template ILIKE '%reminder%'
    AND w.created_at >= '2026-03-07'
  GROUP BY w.reference_id
)
SELECT sc.city, sc.locality AS clinic,
  TO_CHAR(DATE_TRUNC('week', sc.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
  COUNT(*) AS total,
  SUM(COALESCE(r.sent,0))      AS rem_sent,
  SUM(COALESCE(r.delivered,0)) AS rem_delivered,
  SUM(COALESCE(r.rd,0))        AS rem_read,
  SUM(CASE WHEN sc.st='missed' THEN 1 ELSE 0 END)                       AS ns_total,
  SUM(CASE WHEN sc.st='missed' THEN COALESCE(r.sent,0) ELSE 0 END)      AS ns_sent,
  SUM(CASE WHEN sc.st='missed' THEN COALESCE(r.delivered,0) ELSE 0 END) AS ns_delivered,
  SUM(CASE WHEN sc.st='missed' THEN COALESCE(r.rd,0) ELSE 0 END)        AS ns_read
FROM sc LEFT JOIN rem r ON r.appt_id = sc.id
GROUP BY 1,2,3 ORDER BY 1,2,3;
