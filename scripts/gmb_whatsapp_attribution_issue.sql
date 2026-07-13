-- ============================================================================
-- GMB WhatsApp leads: we cannot tell which CLINIC they came from.  (for the dev)
--
-- A GMB *call* lead stores the clinic's unique tracking number in utm_medium
--   (e.g. utm_medium = '8047160881')  →  we map that number to the clinic.
-- A GMB *WhatsApp* lead stores utm_medium = 'whatsapp'  (a constant word, not a
--   number) and nothing else that names a clinic.  So we can only count it at the
--   GMB-national level, never per-clinic.
--
-- Ask: can the click-to-WhatsApp action on each GMB listing pass the clinic
--   (a per-clinic number in utm_medium like the call flow, or the locality in a
--   utm param)?  Then these leads become attributable.
-- ============================================================================

-- QUERY 1 — look at the actual rows.  Pick 15 recent GMB-WhatsApp leads, ALL columns.
-- You will see every row is identical: gmb / whatsapp / gmb_wa / whatsapp, and no
-- column anywhere says which clinic / listing the WhatsApp click came from.
SELECT *
FROM allo_persons.lead
WHERE deleted_at IS NULL
  AND created_at >= DATEADD(week, -3, GETDATE())
  AND lower(coalesce(utm_source,''))  = 'gmb'
  AND lower(coalesce(utm_medium,''))  = 'whatsapp'
ORDER BY created_at DESC
LIMIT 15;


-- QUERY 2 — just the fields that would carry attribution, side by side.
SELECT id,
       phone_no,
       utm_source,        -- 'gmb'
       utm_medium,        -- 'whatsapp'  ← should be the clinic number, like the call flow
       utm_campaign,      -- 'gmb_wa'
       origin,            -- 'whatsapp'
       source_url,        -- NULL
       gclid,             -- NULL
       created_at
FROM allo_persons.lead
WHERE deleted_at IS NULL
  AND created_at >= DATEADD(week, -3, GETDATE())
  AND lower(coalesce(utm_source,''))  = 'gmb'
  AND lower(coalesce(utm_medium,''))  = 'whatsapp'
ORDER BY created_at DESC
LIMIT 15;


-- QUERY 3 — the proof, in one number.  Compare GMB call vs GMB WhatsApp:
--   what % of leads carry a clinic number in utm_medium?
SELECT
  CASE WHEN lower(coalesce(utm_medium,'')) = 'whatsapp' THEN 'GMB WhatsApp'
       ELSE 'GMB call' END                                            AS lead_kind,
  count(*)                                                            AS leads,
  sum(CASE WHEN utm_medium ~ '[0-9]{6}' THEN 1 ELSE 0 END)           AS has_clinic_number,
  round(100.0 * sum(CASE WHEN utm_medium ~ '[0-9]{6}' THEN 1 ELSE 0 END) / count(*), 1) AS pct_attributable
FROM allo_persons.lead
WHERE deleted_at IS NULL
  AND created_at >= DATEADD(week, -5, GETDATE())
  AND lower(coalesce(utm_source,'')) = 'gmb'
GROUP BY 1;
-- Expected:  GMB call ≈ 91% attributable  ·  GMB WhatsApp = 0%.
