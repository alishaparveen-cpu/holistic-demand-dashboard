-- Phase-2 — no-show RECOVERY contact: of missed Screening Calls, how many patients received an
-- outbound call (exotel) within 7 days AFTER the no-show? Fills the recovery funnel's "called back"
-- stage. Patient phone via allo_persons.patient; match exotel outbound by last-10-digits.
WITH ns AS (
  SELECT a.id, a.start_time, RIGHT(p.phone_no,10) AS ph, loc.city, loc.locality,
    TO_CHAR(DATE_TRUNC('week', a.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  JOIN allo_persons.patient p ON p.id = a.patient_id
  WHERE a.deleted_at IS NULL AND LOWER(a.status)='missed'
    AND a.start_time >= '2026-03-16' AND a.start_time < '2026-06-15'
    AND p.phone_no IS NOT NULL AND LEN(p.phone_no) >= 10
    AND LOWER(COALESCE(loc.locality,'')) <> 'online' AND loc.locality IS NOT NULL
),
calls AS (
  SELECT DISTINCT RIGHT("to",10) AS ph, start_time AS ct
  FROM allo_vendors.exotel_calls
  WHERE direction IN ('outbound','outbound-api') AND deleted_at IS NULL
    AND start_time >= '2026-03-16'
)
SELECT ns.city, ns.locality AS clinic, ns.wk,
  COUNT(*) AS noshows,
  SUM(CASE WHEN c.ph IS NOT NULL THEN 1 ELSE 0 END) AS called_back
FROM ns LEFT JOIN calls c
  ON c.ph = ns.ph AND c.ct > ns.start_time AND c.ct <= DATEADD(day,7,ns.start_time)
GROUP BY 1,2,3 ORDER BY 1,2,3;
