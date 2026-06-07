-- Full booking cube: each booked Screening Call classified on FOUR axes at once —
-- channel (lead source) x lead-age group x New/Follow-up x outcome — per clinic/week.
-- Lets the UI focus the whole flow on any chip (click "This week" -> see only those
-- bookings' channels, New/FU split and outcomes). Booked patients only.
WITH sc_all AS (
  SELECT a.id, a.patient_id, a.created_at, a.start_time, LOWER(a.status) AS st,
         LOWER(COALESCE(a.previous_status,'')) AS prev, LOWER(COALESCE(a.reason,'')) AS rsn,
         loc.city, loc.locality
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  WHERE a.deleted_at IS NULL
),
firsts AS (SELECT patient_id, MIN(created_at) AS first_crt FROM sc_all GROUP BY patient_id),
j AS (
  SELECT s.city, s.locality AS clinic,
    TO_CHAR(DATE_TRUNC('week', s.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
    CASE WHEN s.created_at = f.first_crt THEN 'new' ELSE 'fu' END AS seg,
    -- Clean, exhaustive source taxonomy. utm_source is the source of record; origin (whatsapp/call) is a
    -- contact MODE, not a source, so it never decides the channel. ELSE -> Other; empty/no-lead -> No tag.
    CASE
      WHEN l.gclid IS NOT NULL AND l.gclid<>'' THEN 'Google Ads'
      WHEN LOWER(COALESCE(l.utm_source,''))='google' AND LOWER(COALESCE(l.utm_medium,'')) LIKE '%cpc%' THEN 'Google Ads'
      WHEN LOWER(COALESCE(l.utm_source,''))='gmb' THEN 'Google Maps (GMB)'
      WHEN LOWER(COALESCE(l.utm_source,''))='practo' THEN 'Practo'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('fb','facebook','meta','ig','instagram') THEN 'Meta'
      WHEN LOWER(COALESCE(l.utm_source,''))='justdial' THEN 'JustDial'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('organic','google') THEN 'Organic'   -- google non-ad = organic search / listing
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('directwalkin','walkin','walk-in') OR LOWER(COALESCE(l.origin,''))='directwalkin' THEN 'Walk-in'
      WHEN l.id IS NULL OR COALESCE(l.utm_source,'')='' THEN 'No tag'
      ELSE 'Other'
    END AS channel,
    CASE
      WHEN l.id IS NULL OR l.created_at IS NULL THEN 'old'
      WHEN DATEDIFF(day, l.created_at, s.created_at) < 7 THEN 'tw'
      WHEN DATEDIFF(day, l.created_at, s.created_at) < 14 THEN 'lw'
      ELSE 'old'
    END AS agegrp,
    CASE
      WHEN s.st IN ('completed','reconsulted') THEN 'done'
      WHEN s.st='missed' THEN 'missed'
      WHEN s.st='rescheduled' AND s.prev<>'missed' AND NOT (s.rsn LIKE '%provider%' OR s.rsn LIKE '%doctor%' OR s.rsn LIKE '%nonbookable%' OR s.rsn LIKE '%hms%' OR s.rsn LIKE '%block%') THEN 'resched_patient'
      WHEN s.st='rescheduled' AND s.prev<>'missed' THEN 'resched_clinic'
      WHEN s.st='rescheduled' AND s.prev='missed' THEN 'resched_noshow'
      WHEN s.st='cancelled' THEN 'cancelled'
      ELSE 'scheduled'
    END AS outcome
  FROM sc_all s
  JOIN firsts f ON s.patient_id=f.patient_id
  LEFT JOIN allo_persons.patient p ON s.patient_id=p.id
  LEFT JOIN allo_persons.lead l ON p.lead_id=l.id
  WHERE s.start_time >= '2026-03-09' AND s.start_time < '2026-06-01'
    AND LOWER(COALESCE(s.locality,'')) <> 'online' AND s.locality IS NOT NULL
)
SELECT city, clinic, wk, channel, agegrp, seg, outcome, COUNT(*) AS c
FROM j GROUP BY 1,2,3,4,5,6,7 ORDER BY 1,2,3;
