-- Re-booked Screening Calls split by HOW LONG since the patient's prior SC — answers
-- "this week's re-books are re-books from which date?". A re-book = a new SC created within
-- 14 days of the patient's previous SC (reschedule / no-show churn). Bucketed:
--   d0     = same calendar-day re-book
--   d1_6   = 1–6 days later
--   d7_13  = 7–13 days later
-- Per clinic/week (booked, offline clinics). Mirrors the cube's seg='rebook' definition.
WITH sc_all AS (
  SELECT a.id, a.patient_id, a.created_at, a.start_time, loc.city, loc.locality
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  WHERE a.deleted_at IS NULL
),
ranked AS (SELECT *, LAG(created_at) OVER (PARTITION BY patient_id ORDER BY created_at) AS prev_crt FROM sc_all),
j AS (
  SELECT s.city, s.locality AS clinic,
    TO_CHAR(DATE_TRUNC('week', s.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
    CASE WHEN DATEDIFF(day, s.prev_crt, s.created_at) = 0 THEN 'd0'
         WHEN DATEDIFF(day, s.prev_crt, s.created_at) < 7 THEN 'd1_6'
         ELSE 'd7_13' END AS gap
  FROM ranked s
  WHERE s.prev_crt IS NOT NULL
    AND DATEDIFF(day, s.prev_crt, s.created_at) < 14
    AND s.start_time >= '2026-03-09' AND s.start_time < '2026-06-01'
    AND LOWER(COALESCE(s.locality,'')) <> 'online' AND s.locality IS NOT NULL
)
SELECT city, clinic, wk, gap, COUNT(*) AS c
FROM j GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;
