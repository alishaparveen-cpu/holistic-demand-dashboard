-- Diagnostic headline bookings (allBk) + new/repeat + weekend split, on the CLEAN EPISODE basis:
-- each patient's reschedule/re-book chain (consecutive SCs < 14d apart) is collapsed into ONE
-- booking, attributed to the FIRST SC's week, with the chain's FINAL outcome. So one patient-intent
-- = one booking (not one row per reschedule). allBk = new_bk + repeat_bk. Reschedules are NOT counted
-- as bookings — they're rework. "new" = the patient's all-time first episode (full history, incl.
-- online, so early weeks aren't over-counted); "repeat" = a genuine later episode (14d+ apart). 12 weeks.
WITH sc_all AS (
  SELECT app.id, app.patient_id, app.created_at, app.start_time, LOWER(app.status) AS st, loc.city, loc.locality
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
    ROW_NUMBER() OVER (PARTITION BY patient_id, epi_no ORDER BY created_at)     AS rn_asc,
    ROW_NUMBER() OVER (PARTITION BY patient_id, epi_no ORDER BY created_at DESC) AS rn_desc,
    MAX(CASE WHEN st IN ('completed','reconsulted') THEN 1 ELSE 0 END) OVER (PARTITION BY patient_id, epi_no) AS ever_done
  FROM epi
),
first_row AS ( SELECT * FROM ranked WHERE rn_asc=1 ),
last_row  AS ( SELECT patient_id, epi_no, st AS last_st FROM ranked WHERE rn_desc=1 ),
ep AS (
  SELECT f.city, f.locality,
    TO_CHAR(DATE_TRUNC('week', f.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
    (f.epi_no = 1) AS is_new,
    (EXTRACT(DOW FROM f.start_time + INTERVAL '5.5 hours') IN (0,6)) AS is_we,
    (f.ever_done = 1) AS is_done,
    lr.last_st
  FROM first_row f
  JOIN last_row lr ON lr.patient_id=f.patient_id AND lr.epi_no=f.epi_no
  WHERE f.start_time >= '2026-03-16' AND f.start_time < '2026-06-08'
    AND LOWER(COALESCE(f.locality,'')) <> 'online' AND f.locality IS NOT NULL
)
-- episode disposition (done > pending > missed > cancelled), so done+resched+missed+cancelled = allbk.
-- 'resched_bk' here = unresolved / still-pending episodes (reschedules are already collapsed away).
SELECT city, locality, wk,
  COUNT(*) AS allbk,
  SUM(CASE WHEN is_we THEN 1 ELSE 0 END) AS we_allbk,
  SUM(CASE WHEN is_new THEN 1 ELSE 0 END) AS new_bk,
  SUM(CASE WHEN NOT is_new THEN 1 ELSE 0 END) AS repeat_bk,
  SUM(CASE WHEN is_done THEN 1 ELSE 0 END) AS done_bk,
  SUM(CASE WHEN NOT is_done AND last_st NOT IN ('missed','cancelled') THEN 1 ELSE 0 END) AS resched_bk,
  SUM(CASE WHEN NOT is_done AND last_st = 'missed' THEN 1 ELSE 0 END) AS missed_bk,
  SUM(CASE WHEN NOT is_done AND last_st = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_bk,
  SUM(CASE WHEN is_done AND is_new THEN 1 ELSE 0 END) AS done_new_bk,
  SUM(CASE WHEN is_done AND NOT is_new THEN 1 ELSE 0 END) AS done_repeat_bk
FROM ep GROUP BY 1,2,3 ORDER BY 1,2,3 DESC;
