-- Combined booking flow source: each booked Screening Call traced to BOTH its
-- acquisition channel AND its lead-age bucket (via patient.lead_id -> lead), per
-- clinic/week, with outcome split. Lets the dashboard draw channel -> age -> booking
-- -> outcome as one connected flow, and derive the channel-only / age-only marginals.
WITH sc_all AS (
  SELECT a.id, a.patient_id, a.created_at AS booked_at, a.start_time, LOWER(a.status) AS st,
         LOWER(COALESCE(a.previous_status,'')) AS prev, LOWER(COALESCE(a.reason,'')) AS rsn,
         loc.city, loc.locality
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  WHERE a.deleted_at IS NULL
),
j AS (
  SELECT s.city, s.locality AS clinic,
    TO_CHAR(DATE_TRUNC('week', s.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
    s.st, s.prev,
    (s.rsn LIKE '%provider%' OR s.rsn LIKE '%doctor%' OR s.rsn LIKE '%nonbookable%' OR s.rsn LIKE '%hms%' OR s.rsn LIKE '%block%') AS is_clinic_resched,
    CASE
      WHEN l.gclid IS NOT NULL AND l.gclid<>'' THEN 'Google Ads'
      WHEN LOWER(COALESCE(l.utm_source,''))='google' AND LOWER(COALESCE(l.utm_medium,'')) LIKE '%cpc%' THEN 'Google Ads'
      WHEN LOWER(COALESCE(l.utm_source,''))='google' THEN 'Google organic'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('fb','facebook','meta','ig','instagram') THEN 'Meta'
      WHEN LOWER(COALESCE(l.utm_source,''))='practo' THEN 'Practo'
      WHEN LOWER(COALESCE(l.utm_source,''))='gmb' THEN 'Google Maps (GMB)'
      WHEN LOWER(COALESCE(l.origin,''))='whatsapp' OR LOWER(COALESCE(l.utm_source,''))='whatsapp' THEN 'WhatsApp'
      WHEN LOWER(COALESCE(l.utm_source,''))='organic' THEN 'Organic'
      WHEN l.id IS NULL THEN 'No lead record'
      WHEN COALESCE(l.utm_source,'')='' THEN 'Unknown'
      ELSE 'Other'
    END AS channel,
    CASE
      WHEN l.id IS NULL OR l.created_at IS NULL THEN 'Unknown'
      WHEN DATEDIFF(day, l.created_at, s.booked_at) < 7 THEN '1 · Same week'
      WHEN DATEDIFF(day, l.created_at, s.booked_at) < 14 THEN '2 · Last week'
      WHEN DATEDIFF(day, l.created_at, s.booked_at) < 28 THEN '3 · 2-4 weeks'
      WHEN DATEDIFF(day, l.created_at, s.booked_at) < 90 THEN '4 · 1-3 months'
      ELSE '5 · 3+ months'
    END AS agebucket
  FROM sc_all s
  LEFT JOIN allo_persons.patient p ON s.patient_id=p.id
  LEFT JOIN allo_persons.lead l ON p.lead_id=l.id
  WHERE s.start_time >= '2026-03-09' AND s.start_time < '2026-06-01'
    AND LOWER(COALESCE(s.locality,'')) <> 'online' AND s.locality IS NOT NULL
)
SELECT city, clinic, wk, channel, agebucket,
  COUNT(*) AS total,
  SUM(CASE WHEN st IN ('completed','reconsulted') THEN 1 ELSE 0 END) AS done,
  SUM(CASE WHEN st='missed' THEN 1 ELSE 0 END) AS missed,
  SUM(CASE WHEN st='rescheduled' AND prev<>'missed' AND NOT is_clinic_resched THEN 1 ELSE 0 END) AS resched_patient,
  SUM(CASE WHEN st='rescheduled' AND prev<>'missed' AND is_clinic_resched THEN 1 ELSE 0 END) AS resched_clinic,
  SUM(CASE WHEN st='rescheduled' AND prev='missed' THEN 1 ELSE 0 END) AS resched_noshow,
  SUM(CASE WHEN st='cancelled' THEN 1 ELSE 0 END) AS cancelled,
  SUM(CASE WHEN st IN ('scheduled','confirmed','in_progress','provider_joined') THEN 1 ELSE 0 END) AS scheduled
FROM j
GROUP BY 1,2,3,4,5 ORDER BY 1,2,3,4,5;
