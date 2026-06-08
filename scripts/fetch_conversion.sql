-- Clinic Scorecard — the REVENUE funnel: completed Screening Call -> converted to ongoing
-- treatment (Follow Up / Therapy) within 30 days, per clinic/week. The free first call is only
-- worth it if it turns into continuing care. Recent weeks are right-censored (30d window not
-- elapsed) — the build script flags those.
WITH sc AS (
  SELECT a.patient_id, a.start_time AS sc_time, loc.city, loc.locality,
         TO_CHAR(DATE_TRUNC('week', a.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  WHERE a.deleted_at IS NULL AND LOWER(a.status) IN ('completed','reconsulted')
    AND a.start_time >= '2026-03-16' AND a.start_time < '2026-06-08'
    AND LOWER(COALESCE(loc.locality,'')) <> 'online' AND loc.locality IS NOT NULL
),
conv AS (
  SELECT DISTINCT sc.patient_id, sc.sc_time
  FROM sc JOIN allo_consultations.appointments b ON b.patient_id = sc.patient_id
  JOIN allo_consultations.types tb ON b.type_id=tb.id AND tb.name IN ('Follow Up','Therapy','Mental Health Therapy')
  WHERE b.deleted_at IS NULL AND b.start_time > sc.sc_time
    AND b.start_time <= sc.sc_time + INTERVAL '30 days'
)
SELECT sc.city, sc.locality AS clinic, sc.wk,
  COUNT(*) AS completed_sc,
  SUM(CASE WHEN c.patient_id IS NOT NULL THEN 1 ELSE 0 END) AS converted
FROM sc LEFT JOIN conv c ON c.patient_id=sc.patient_id AND c.sc_time=sc.sc_time
GROUP BY 1,2,3 ORDER BY 1,2,3;
