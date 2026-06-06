-- Per clinic: bookings (and done) by day-of-week × hour-of-day (IST), last 8 weeks → peak-slot map.
SELECT loc.city||'|'||loc.locality AS k,
  EXTRACT(dow FROM a.start_time + INTERVAL '5.5 hours')::int AS dow,   -- 0=Sun … 6=Sat
  EXTRACT(hour FROM a.start_time + INTERVAL '5.5 hours')::int AS hr,
  COUNT(*) AS booked,
  SUM(CASE WHEN LOWER(a.status) IN ('completed','reconsulted') THEN 1 ELSE 0 END) AS done
FROM allo_consultations.appointments a
JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
WHERE a.deleted_at IS NULL AND a.start_time >= '2026-04-06' AND a.start_time < '2026-06-01'
  AND LOWER(COALESCE(loc.locality,''))<>'online' AND loc.locality IS NOT NULL
GROUP BY 1,2,3 ORDER BY 1,2,3;
