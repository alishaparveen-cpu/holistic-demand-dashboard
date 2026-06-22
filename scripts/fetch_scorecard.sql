-- Clinic Scorecard dispositions per clinic/week, on the CLEAN EPISODE basis: each patient's
-- reschedule/re-book chain (consecutive SCs < 14d apart) collapses into ONE booking, attributed to
-- the first SC's week, with the chain's FINAL outcome. So total = unique patient-intents (not rows).
-- Reschedules are collapsed (they're rework, surfaced separately), so the resched_* disposition
-- columns are 0 here; an unresolved chain lands in 'scheduled' (pending). recovered_done = an episode
-- that ended completed despite a no-show somewhere in its chain. new = patient's first-ever episode.
-- Columns kept identical to the row-level version so build_scorecard.py is unchanged.
WITH sc_all AS (
  SELECT a.id, a.patient_id, a.created_at, a.start_time, LOWER(a.status) AS st, loc.city, loc.locality
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  WHERE a.deleted_at IS NULL
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
    MAX(CASE WHEN st IN ('completed','reconsulted') THEN 1 ELSE 0 END) OVER (PARTITION BY patient_id, epi_no) AS ever_done,
    MAX(CASE WHEN st='missed' THEN 1 ELSE 0 END) OVER (PARTITION BY patient_id, epi_no) AS ever_missed
  FROM epi
),
first_row AS ( SELECT * FROM ranked WHERE rn_asc=1 ),
last_row  AS ( SELECT patient_id, epi_no, st AS last_st FROM ranked WHERE rn_desc=1 ),
ep AS (
  SELECT f.city, f.locality AS clinic,
    TO_CHAR(DATE_TRUNC('week', f.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
    (f.epi_no = 1) AS is_new, f.ever_done, f.ever_missed, lr.last_st
  FROM first_row f
  JOIN last_row lr ON lr.patient_id=f.patient_id AND lr.epi_no=f.epi_no
  WHERE f.start_time >= '2026-03-23' AND f.start_time < '2026-06-22'
    AND LOWER(COALESCE(f.locality,''))<>'online' AND f.locality IS NOT NULL
)
SELECT city, clinic, wk,
  COUNT(*) AS total,
  SUM(CASE WHEN is_new THEN 1 ELSE 0 END) AS new_bk,
  SUM(CASE WHEN NOT is_new THEN 1 ELSE 0 END) AS followup_bk,
  SUM(CASE WHEN ever_done=1 THEN 1 ELSE 0 END) AS done,
  SUM(CASE WHEN ever_done=1 AND is_new THEN 1 ELSE 0 END) AS done_new,
  SUM(CASE WHEN ever_done=1 AND NOT is_new THEN 1 ELSE 0 END) AS done_followup,
  SUM(CASE WHEN ever_done=0 AND last_st='missed' THEN 1 ELSE 0 END) AS missed,
  0 AS resched_noshow,
  0 AS resched_clinic,
  0 AS resched_patient,
  SUM(CASE WHEN ever_done=1 AND ever_missed=1 THEN 1 ELSE 0 END) AS recovered_done,
  SUM(CASE WHEN ever_done=0 AND last_st='cancelled' THEN 1 ELSE 0 END) AS cancelled,
  SUM(CASE WHEN ever_done=0 AND last_st NOT IN ('missed','cancelled') THEN 1 ELSE 0 END) AS scheduled
FROM ep GROUP BY 1,2,3 ORDER BY 1,2,3
