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
ranked AS (SELECT *, LAG(created_at) OVER (PARTITION BY patient_id ORDER BY created_at) AS prev_crt FROM sc_all),
j AS (
  SELECT s.city, s.locality AS clinic,
    TO_CHAR(DATE_TRUNC('week', s.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
    -- new = patient's first-ever SC; rebook = within 14d of the prior SC (reschedule / no-show re-book churn);
    -- return = a genuine repeat 14+ days later. Splits the old 'follow-up' so Total stops double-counting churn.
    CASE WHEN s.prev_crt IS NULL THEN 'new'
         WHEN DATEDIFF(day, s.prev_crt, s.created_at) < 14 THEN 'rebook'
         ELSE 'return' END AS seg,
    -- Clean, exhaustive source taxonomy. utm_source is the source of record; origin (whatsapp/call) is a
    -- contact MODE, not a source, so it never decides the channel. ELSE -> Other; empty/no-lead -> No tag.
    CASE
      WHEN l.gclid IS NOT NULL AND l.gclid<>'' THEN 'Google Ads'
      WHEN LOWER(COALESCE(l.utm_source,''))='google' AND LOWER(COALESCE(l.utm_medium,'')) LIKE '%cpc%' THEN 'Google Ads'
      WHEN LOWER(COALESCE(l.utm_source,''))='google' AND LOWER(COALESCE(l.utm_campaign,''))='inbound_call' THEN 'Google Ads'  -- google-source inbound calls (no gclid, medium=number not cpc); GMB calls are utm_source='gmb' so unaffected
      WHEN LOWER(COALESCE(l.utm_source,''))='bing' THEN 'Bing Ads'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('gmb','googlelisting','google listing','google_listing') THEN 'Google Maps (GMB)'
      WHEN LOWER(COALESCE(l.utm_source,''))='practo' THEN 'Practo'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('fb','facebook','meta','ig','instagram') THEN 'Meta'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('justdial','jd') THEN 'JustDial'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('alloreferral','allorefferal','doctorreferral','referral') THEN 'Referral'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('chatgpt.com','youtube','moj') THEN 'AI / Social'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('organic','google','blog') THEN 'Organic'   -- google non-ad / blog / organic search
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('directwalkin','walkin','walk-in') OR LOWER(COALESCE(l.origin,''))='directwalkin' THEN 'Walk-in'
      WHEN LOWER(COALESCE(l.utm_source,''))='others' THEN 'Other (untracked)'
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
  FROM ranked s
  LEFT JOIN allo_persons.patient p ON s.patient_id=p.id
  LEFT JOIN allo_persons.lead l ON p.lead_id=l.id
  WHERE s.start_time >= '2026-03-23' AND s.start_time < '2026-06-29'
    AND LOWER(COALESCE(s.locality,'')) <> 'online' AND s.locality IS NOT NULL
)
SELECT city, clinic, wk, channel, agegrp, seg, outcome, COUNT(*) AS c
FROM j GROUP BY 1,2,3,4,5,6,7 ORDER BY 1,2,3;
