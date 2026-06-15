-- Retention depth: of patients whose Screening Call COMPLETED in a cohort week, how many
-- subsequent treatment appointments (Follow Up / Therapy, completed) did they have within 60 days?
-- Bucketed 0 / 1 / 2 / 3+, per clinic/week. Recent ~9 weeks right-censored (60d window) — flagged.
WITH sc AS (
  SELECT a.patient_id, a.start_time AS sc_time, loc.city, loc.locality,
         TO_CHAR(DATE_TRUNC('week', a.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  WHERE a.deleted_at IS NULL AND LOWER(a.status) IN ('completed','reconsulted')
    AND a.start_time >= '2026-03-16' AND a.start_time < '2026-06-15'
    AND LOWER(COALESCE(loc.locality,'')) <> 'online' AND loc.locality IS NOT NULL
),
tx AS (
  SELECT sc.patient_id, sc.sc_time, COUNT(*) AS n
  FROM sc
  JOIN allo_consultations.appointments b
    ON b.patient_id = sc.patient_id AND b.deleted_at IS NULL
   AND LOWER(b.status) IN ('completed','reconsulted')
   AND b.start_time > sc.sc_time AND b.start_time <= sc.sc_time + INTERVAL '60 days'
  JOIN allo_consultations.types tb ON tb.id = b.type_id
   AND tb.name IN ('Follow Up','Therapy','Mental Health Therapy')
  GROUP BY 1,2
)
SELECT sc.city, sc.locality AS clinic, sc.wk,
  COUNT(*) AS cohort,
  SUM(CASE WHEN COALESCE(tx.n,0)=0 THEN 1 ELSE 0 END) AS d0,
  SUM(CASE WHEN tx.n=1 THEN 1 ELSE 0 END) AS d1,
  SUM(CASE WHEN tx.n=2 THEN 1 ELSE 0 END) AS d2,
  SUM(CASE WHEN tx.n>=3 THEN 1 ELSE 0 END) AS d3plus,
  SUM(COALESCE(tx.n,0)) AS total_tx_visits
FROM sc LEFT JOIN tx ON tx.patient_id=sc.patient_id AND tx.sc_time=sc.sc_time
GROUP BY 1,2,3 ORDER BY 1,2,3;
