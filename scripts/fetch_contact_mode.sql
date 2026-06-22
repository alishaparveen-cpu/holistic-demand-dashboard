-- Clinic × WEEK × original contact mode of patients who booked an SC. Mode from the patient's
-- lead.origin (how the lead was created). Week = booking slot week (Mon), matches the scorecard.
WITH sc AS (
  SELECT DISTINCT a.patient_id, loc.city, loc.locality AS clinic,
    TO_CHAR(DATE_TRUNC('week', a.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  WHERE a.deleted_at IS NULL AND a.start_time >= '2026-03-23' AND a.start_time < '2026-06-22'
    AND LOWER(COALESCE(loc.locality,''))<>'online' AND loc.locality IS NOT NULL
),
ph AS (SELECT id, RIGHT(phone_no,10) AS p10 FROM allo_persons.patient WHERE phone_no IS NOT NULL),
ld AS (
  SELECT RIGHT(phone_no,10) AS p10,
    CASE WHEN LOWER(COALESCE(origin,'')) LIKE '%exotel%' OR origin ~ '^[0-9 +]{6,}$' THEN 'Call'
         WHEN LOWER(COALESCE(origin,'')) LIKE '%whatsapp%' THEN 'WhatsApp'
         WHEN LOWER(COALESCE(origin,'')) LIKE '%practo%' THEN 'Practo'
         WHEN LOWER(COALESCE(origin,'')) LIKE '%retool%' OR LOWER(COALESCE(origin,'')) LIKE '%dashboard%' THEN 'Walk-in/Ops'
         WHEN user_flow IS NOT NULL OR LOWER(COALESCE(origin,'')) LIKE '%http%' OR LOWER(COALESCE(origin,'')) LIKE '%allohealth%'
              OR LOWER(COALESCE(origin,'')) LIKE '%allo health%' OR LOWER(COALESCE(origin,'')) LIKE '%website%'
              OR LOWER(COALESCE(origin,'')) LIKE '%sexual%' OR LOWER(COALESCE(origin,'')) LIKE '%sexologist%'
              OR LOWER(COALESCE(origin,'')) LIKE '%sti%' OR LOWER(COALESCE(origin,'')) LIKE '%mental%'
              OR LOWER(COALESCE(origin,'')) LIKE '%doctor%' OR LOWER(COALESCE(origin,'')) LIKE '%clinic%'
              OR LOWER(COALESCE(origin,'')) LIKE '%evaluation%' OR LOWER(COALESCE(origin,'')) LIKE '%login%' THEN 'Website'
         WHEN origin IS NULL OR TRIM(origin)='' THEN 'Unknown'
         ELSE 'Other' END AS mode,
    ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY created_at DESC) AS rn
  FROM allo_persons.lead WHERE phone_no IS NOT NULL AND LEN(phone_no)>=10
)
SELECT sc.city||'|'||sc.clinic AS k, sc.wk, COALESCE(ld.mode,'Unknown') AS mode, COUNT(*) AS n
FROM sc JOIN ph ON ph.id=sc.patient_id LEFT JOIN ld ON ld.p10=ph.p10 AND ld.rn=1
GROUP BY 1,2,3 ORDER BY 1,2,3;
