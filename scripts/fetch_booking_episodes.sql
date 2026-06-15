-- CLEAN booking funnel: collapse each patient's reschedule / re-book chain into ONE booking
-- "episode", so one patient-intent = one booking (not one row per reschedule). An episode = a
-- maximal run of a patient's Screening Calls where each is < 14 days after the previous one.
--   • attributed to the episode's FIRST SC  → its week / channel / lead-age (where demand happened)
--   • seg   = new (patient's first-ever episode) | return (a genuine later visit, 14d+ after the last)
--   • outcome = done if the patient EVER completed in the chain; else the chain's final status
--               (missed / cancelled / pending) — their true end state, counted once
--   • resched_events = rows in the chain − 1  → operational rework, NOT extra demand
-- Booked patients only, offline clinics. Mirrors fetch_booking_cube.sql but episode-collapsed.
WITH sc_all AS (
  SELECT a.id, a.patient_id, a.created_at, a.start_time, LOWER(a.status) AS st,
         loc.city, loc.locality, p.lead_id
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  LEFT JOIN allo_persons.patient p ON p.id=a.patient_id
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
    ROW_NUMBER() OVER (PARTITION BY patient_id, epi_no ORDER BY created_at)      AS rn_asc,
    ROW_NUMBER() OVER (PARTITION BY patient_id, epi_no ORDER BY created_at DESC)  AS rn_desc,
    COUNT(*)     OVER (PARTITION BY patient_id, epi_no)                           AS chain_len,
    MAX(CASE WHEN st IN ('completed','reconsulted') THEN 1 ELSE 0 END) OVER (PARTITION BY patient_id, epi_no) AS ever_done
  FROM epi
),
first_row AS ( SELECT * FROM ranked WHERE rn_asc=1 ),
last_row  AS ( SELECT patient_id, epi_no, st AS last_st FROM ranked WHERE rn_desc=1 ),
joined AS (
  SELECT f.city, f.locality AS clinic,
    TO_CHAR(DATE_TRUNC('week', f.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
    CASE WHEN f.epi_no = 1 THEN 'new' ELSE 'return' END AS seg,
    CASE WHEN f.ever_done = 1 THEN 'done'
         WHEN lr.last_st = 'cancelled' THEN 'cancelled'
         WHEN lr.last_st = 'missed' THEN 'missed'
         WHEN lr.last_st = 'rescheduled' THEN 'resched'   -- deferred >14d (next visit, if any, is a separate 'return')
         ELSE 'open' END AS outcome,                      -- still scheduled / in-progress: upcoming or status never finalized
    (f.chain_len - 1) AS resched_events,
    CASE
      WHEN l.gclid IS NOT NULL AND l.gclid<>'' THEN 'Google Ads'
      WHEN LOWER(COALESCE(l.utm_source,''))='google' AND LOWER(COALESCE(l.utm_medium,'')) LIKE '%cpc%' THEN 'Google Ads'
      WHEN LOWER(COALESCE(l.utm_source,''))='bing' THEN 'Bing Ads'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('gmb','googlelisting','google listing','google_listing') THEN 'Google Maps (GMB)'
      WHEN LOWER(COALESCE(l.utm_source,''))='practo' THEN 'Practo'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('fb','facebook','meta','ig','instagram') THEN 'Meta'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('justdial','jd') THEN 'JustDial'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('alloreferral','allorefferal','doctorreferral','referral') THEN 'Referral'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('chatgpt.com','youtube','moj') THEN 'AI / Social'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('organic','google','blog') THEN 'Organic'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('directwalkin','walkin','walk-in') THEN 'Walk-in'
      WHEN LOWER(COALESCE(l.utm_source,''))='others' THEN 'Other (untracked)'
      WHEN l.id IS NULL OR COALESCE(l.utm_source,'')='' THEN 'No tag'
      ELSE 'Other'
    END AS channel,
    CASE
      WHEN l.id IS NULL OR l.created_at IS NULL THEN 'old'
      WHEN DATEDIFF(day, l.created_at, f.created_at) < 7 THEN 'tw'
      WHEN DATEDIFF(day, l.created_at, f.created_at) < 14 THEN 'lw'
      ELSE 'old'
    END AS agegrp
  FROM first_row f
  JOIN last_row lr ON lr.patient_id=f.patient_id AND lr.epi_no=f.epi_no
  LEFT JOIN allo_persons.lead l ON f.lead_id=l.id
  WHERE f.start_time >= '2026-03-16' AND f.start_time < '2026-06-15'
    AND LOWER(COALESCE(f.locality,'')) <> 'online' AND f.locality IS NOT NULL
)
SELECT city, clinic, wk, channel, agegrp, seg, outcome,
  COUNT(*) AS episodes, SUM(resched_events) AS resched_events
FROM joined GROUP BY 1,2,3,4,5,6,7 ORDER BY 1,2,3;
