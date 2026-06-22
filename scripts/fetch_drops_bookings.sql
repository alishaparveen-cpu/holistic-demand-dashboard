-- First-time / total / done SC bookings on the CLEAN EPISODE basis, grouped by
-- city × locality(clinic) × provider(doctor) × slot-week — so the Diagnostic View can show
-- "1st Time Bookings" (the city-head headline) at every level. Same episode logic as
-- fetch_diag_bookings.sql: each patient's reschedule chain (consecutive SCs <14d apart) collapses
-- into ONE booking at the FIRST SC's week, with the chain's final outcome. Doctor = provider of
-- that first SC. Online excluded (offline clinic demand only). 12 weeks.
--   first_bk = patient's all-time FIRST episode  (= bkNew = "1st Time Bookings")
--   all_bk   = every episode                     (= allBk = "Overall Bookings" = new + repeat)
--   done_new = first episodes that completed      (for a coherent New→Done conversion)
WITH sc_all AS (
  SELECT app.id, app.patient_id, app.provider_id, app.created_at, app.start_time,
         LOWER(app.status) AS st, loc.city, loc.locality
  FROM allo_consultations.appointments app
  JOIN allo_health.locations loc ON app.location_id=loc.id AND loc.deleted_at IS NULL
  JOIN allo_consultations.types typ ON app.type_id=typ.id AND typ.name='Screening Call'
  WHERE app.deleted_at IS NULL
),
flagged AS (
  SELECT *, LAG(created_at) OVER (PARTITION BY patient_id ORDER BY created_at) AS prev_crt FROM sc_all
),
bounds AS (
  SELECT *, CASE WHEN prev_crt IS NULL OR DATEDIFF(day,prev_crt,created_at) >= 14 THEN 1 ELSE 0 END AS new_epi
  FROM flagged
),
epi AS (
  SELECT *, SUM(new_epi) OVER (PARTITION BY patient_id ORDER BY created_at ROWS UNBOUNDED PRECEDING) AS epi_no
  FROM bounds
),
ranked AS (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY patient_id, epi_no ORDER BY created_at) AS rn_asc,
    MAX(CASE WHEN st IN ('completed','reconsulted') THEN 1 ELSE 0 END) OVER (PARTITION BY patient_id, epi_no) AS ever_done
  FROM epi
),
first_row AS ( SELECT * FROM ranked WHERE rn_asc=1 )
SELECT f.city, f.locality,
  COALESCE(NULLIF(TRIM(pr.name),''),'(unassigned)') AS doctor,
  TO_CHAR(DATE_TRUNC('week', f.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
  SUM(CASE WHEN f.epi_no = 1 THEN 1 ELSE 0 END)                       AS first_bk,
  COUNT(*)                                                            AS all_bk,
  SUM(CASE WHEN f.epi_no = 1 AND f.ever_done = 1 THEN 1 ELSE 0 END)   AS done_new
FROM first_row f
LEFT JOIN allo_persons.providers pr ON pr.id = f.provider_id
WHERE f.start_time >= '2026-03-23' AND f.start_time < '2026-06-22'
  AND LOWER(COALESCE(f.locality,'')) <> 'online' AND f.locality IS NOT NULL
GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;
