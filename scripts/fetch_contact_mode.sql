-- Clinic-level: of patients who booked an SC at each clinic, how did they ORIGINALLY reach us?
-- appointment(clinic) → patient phone → lead.origin → contact mode. Last 4 weeks.
WITH sc AS (
  SELECT DISTINCT a.patient_id, loc.city, loc.locality AS clinic
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  WHERE a.deleted_at IS NULL AND a.created_at >= '2026-05-04'
    AND LOWER(COALESCE(loc.locality,''))<>'online' AND loc.locality IS NOT NULL
),
ph AS (SELECT id, RIGHT(phone_no,10) AS p10 FROM allo_persons.patient WHERE phone_no IS NOT NULL),
ld AS (
  SELECT RIGHT(phone_no,10) AS p10,
    CASE WHEN LOWER(COALESCE(origin,'')) LIKE '%whatsapp%' THEN 'WhatsApp'
         WHEN LOWER(COALESCE(origin,'')) LIKE '%exotel%' OR origin ~ '^[0-9 +]{6,}$' THEN 'Call'
         WHEN LOWER(COALESCE(origin,'')) LIKE '%practo%' THEN 'Practo'
         WHEN user_flow IS NOT NULL OR LOWER(COALESCE(origin,'')) LIKE '%allohealth%' OR LOWER(COALESCE(origin,'')) LIKE '%http%' OR origin LIKE '%Allo Health%' THEN 'Website'
         ELSE 'Other' END AS mode,
    ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY created_at DESC) AS rn
  FROM allo_persons.lead WHERE phone_no IS NOT NULL AND LEN(phone_no)>=10
)
SELECT sc.city||'|'||sc.clinic AS k, COALESCE(ld.mode,'Unknown') AS mode, COUNT(*) AS n
FROM sc JOIN ph ON ph.id=sc.patient_id LEFT JOIN ld ON ld.p10=ph.p10 AND ld.rn=1
GROUP BY 1,2 ORDER BY 1,2;
