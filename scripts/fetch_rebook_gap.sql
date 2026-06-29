-- Reschedule (re-book) events split by (1) the booking SEGMENT they belong to — new (first-time)
-- vs return (genuine repeat) — and (2) HOW LONG since the prior SC. A reschedule = a non-first SC
-- inside an episode (consecutive SCs <14d apart). Attributed to the episode's FIRST-SC week, so it
-- lines up with the clean booking flow. Per clinic/week/seg/gap (booked, offline).
--   seg : new = patient's first-ever episode · return = a later (14d+) episode
--   gap : d0 same-day · d1_6 1–6 days later · d7_13 7–13 days later
WITH sc_all AS (
  SELECT a.id, a.patient_id, a.created_at, a.start_time, loc.city, loc.locality
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
    ROW_NUMBER() OVER (PARTITION BY patient_id, epi_no ORDER BY created_at) AS rn_asc,
    FIRST_VALUE(start_time) OVER (PARTITION BY patient_id, epi_no ORDER BY created_at
                                  ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS epi_first_start,
    FIRST_VALUE(city)       OVER (PARTITION BY patient_id, epi_no ORDER BY created_at
                                  ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS epi_city,
    FIRST_VALUE(locality)   OVER (PARTITION BY patient_id, epi_no ORDER BY created_at
                                  ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS epi_clinic
  FROM epi
)
SELECT s.epi_city AS city, s.epi_clinic AS clinic,
  TO_CHAR(DATE_TRUNC('week', s.epi_first_start + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
  CASE WHEN s.epi_no = 1 THEN 'new' ELSE 'return' END AS seg,
  CASE WHEN DATEDIFF(day, s.prev_crt, s.created_at) = 0 THEN 'd0'
       WHEN DATEDIFF(day, s.prev_crt, s.created_at) < 7 THEN 'd1_6'
       ELSE 'd7_13' END AS gap,
  COUNT(*) AS c
FROM ranked s
WHERE s.rn_asc > 1                       -- reschedule events = non-first SCs within an episode
  AND s.epi_first_start >= '2026-03-23' AND s.epi_first_start < '2026-06-29'
  AND LOWER(COALESCE(s.epi_clinic,'')) <> 'online' AND s.epi_clinic IS NOT NULL
GROUP BY 1,2,3,4,5 ORDER BY 1,2,3,4,5;
