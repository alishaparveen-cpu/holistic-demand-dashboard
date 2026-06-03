WITH sc AS (
  SELECT app.id, app.patient_id, loc.city, loc.locality,
    app.created_at + INTERVAL '5.5 hours' AS crt,
    DATE_TRUNC('week', app.start_time + INTERVAL '5.5 hours') AS wk_mon,
    app.status,
    CASE WHEN app.updated_at > app.start_time AND app.status NOT IN ('COMPLETED','RECONSULTED') THEN 1 ELSE 0 END AS is_noshow,
    ROW_NUMBER() OVER (PARTITION BY app.patient_id ORDER BY app.created_at ASC) AS pat_rank
  FROM allo_consultations.appointments app
  JOIN allo_health.locations loc ON app.location_id=loc.id AND loc.deleted_at IS NULL
  JOIN allo_consultations.types typ ON app.type_id=typ.id AND typ.name='Screening Call'
  WHERE app.deleted_at IS NULL
    AND app.start_time >= '2026-03-09' AND app.start_time < '2026-06-02'
    AND LOWER(COALESCE(loc.locality,''))<>'online' AND loc.locality IS NOT NULL
)
SELECT city, locality, TO_CHAR(wk_mon,'YYYY-MM-DD') wk,
  SUM(CASE WHEN pat_rank=1 THEN 1 ELSE 0 END) AS new_bk,
  SUM(CASE WHEN pat_rank>1 THEN 1 ELSE 0 END) AS repeat_bk,
  SUM(CASE WHEN LOWER(status)='cancelled' THEN 1 ELSE 0 END) AS cancelled,
  COUNT(*) AS total
FROM sc GROUP BY 1,2,3 ORDER BY 1,2,3 DESC
