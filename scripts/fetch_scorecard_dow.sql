-- Clinic Scorecard — day-of-week booking outcomes per clinic (last ~8 weeks), to spot a
-- consistent no-show / low-B2D day (an ops fix, not a demand one). dow: 0=Sun .. 6=Sat (IST).
SELECT loc.city, loc.locality AS clinic,
  EXTRACT(DOW FROM (a.start_time + INTERVAL '5.5 hours')) AS dow,
  COUNT(*) AS booked,
  SUM(CASE WHEN LOWER(a.status) IN ('completed','reconsulted') THEN 1 ELSE 0 END) AS done,
  SUM(CASE WHEN LOWER(a.status)='missed' THEN 1 ELSE 0 END) AS missed
FROM allo_consultations.appointments a
JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
WHERE a.deleted_at IS NULL AND a.start_time >= '2026-04-13' AND a.start_time < '2026-06-15'
  AND LOWER(COALESCE(loc.locality,''))<>'online' AND loc.locality IS NOT NULL
GROUP BY 1,2,3 ORDER BY 1,2,3
