-- ============================================================================
-- Practo leads: we cannot attribute them to a CITY / CLINIC / DOCTOR.  (for the dev)
--
-- WHY THE DASHBOARD SHOWS PRACTO ONLY AT THE NATIONAL LEVEL
-- --------------------------------------------------------------------------
-- Every other paid channel hands us a per-clinic signal on the lead row:
--    GMB call  → utm_medium = the clinic's own tracking number (e.g. 8047160881)
--    Google    → city + category tokens in the campaign / source_url
--    Meta      → fbclid we can join back to the ad set
-- Practo hands us NONE of these.  A Practo lead arrives one of three ways, and
-- not one of them names the clinic it came from:
--
--    (a) utm_medium = 08071176846   → a SINGLE shared Practo phone line used by
--        ALL clinics nationally (not a per-clinic number like the GMB call flow)
--    (b) utm_medium = blank          → nothing at all
--    (c) utm_medium = 'retool - patient dashboard' → hand-keyed in the ops tool
--
-- So the lead row itself is 0% clinic-attributable.  The Practo *tab* in the
-- dashboard only recovers a clinic for the leads that later BOOKED — by matching
-- the lead's phone to the patient and reading the clinic off that Screening-Call
-- appointment.  Leads that never booked stay national, and even the booked ones
-- inherit the *booking* clinic, not the Practo *listing* the patient saw.
--
-- Two separate fixes are needed, one at the source and one in our mapping:
--   FIX 1 (source, Practo side): pass a per-clinic identifier on lead creation —
--          either a per-clinic tracking number in utm_medium (mirror the GMB call
--          flow) OR the Practo Practice name/locality in a utm param.
--   FIX 2 (our side): Practo's "Practice / Locality" labels don't match our
--          allo_health.locations.locality strings, so even when we DO get a
--          Practo practice name we need an alias map (Practo-practice → our
--          city|locality) before it will join.  Single-clinic cities are safe to
--          auto-map; multi-clinic cities (e.g. Bangalore) need the alias table.
-- ============================================================================


-- QUERY 1 — the proof, in one table.  How does each Practo lead identify itself,
--   and what fraction carries anything clinic-specific?  (last 5 weeks)
-- Expected: ~0% clinic-attributable — the only "number" is the one shared line.
SELECT
  CASE
    WHEN utm_medium ~ '[0-9]{6}'                              THEN 'phone number in utm_medium'
    WHEN lower(coalesce(utm_medium,'')) LIKE 'retool%'        THEN 'retool - hand-keyed'
    WHEN coalesce(utm_medium,'') = ''                         THEN '(blank)'
    ELSE lower(utm_medium) END                                        AS how_it_identifies,
  count(*)                                                            AS leads,
  count(DISTINCT regexp_replace(coalesce(utm_medium,''),'[^0-9]',''))
    FILTER (WHERE utm_medium ~ '[0-9]{6}')                            AS distinct_numbers
FROM allo_persons.lead
WHERE deleted_at IS NULL
  AND created_at >= DATEADD(week, -5, GETDATE())
  AND lower(coalesce(utm_source,'')) = 'practo'
GROUP BY 1
ORDER BY 2 DESC;
-- The 'phone number' row will show distinct_numbers = 1  →  08071176846, one
-- national line shared by every clinic.  A per-clinic flow would show ~70 numbers.


-- QUERY 2 — look at the actual rows.  15 recent Practo leads, the columns that
--   *would* carry attribution, side by side.  Confirm nothing names a clinic.
SELECT id,
       phone_no,
       utm_source,    -- 'practo'
       utm_medium,    -- 08071176846 (shared) | blank | 'retool - patient dashboard'
       utm_campaign,
       source_url,    -- no clinic / practice token
       created_at
FROM allo_persons.lead
WHERE deleted_at IS NULL
  AND created_at >= DATEADD(week, -3, GETDATE())
  AND lower(coalesce(utm_source,'')) = 'practo'
ORDER BY created_at DESC
LIMIT 15;


-- QUERY 3 — how much we recover ANYWAY via the phone→booking join, and how much
--   is lost.  A Practo lead becomes clinic-attributable ONLY if the same phone
--   later appears on a Screening-Call appointment (we then borrow that clinic).
--   Everything else is unattributable.  This quantifies the gap for the fix.
WITH practo AS (
  SELECT DISTINCT RIGHT(regexp_replace(phone_no,'[^0-9]',''),10) AS ph10
  FROM allo_persons.lead
  WHERE deleted_at IS NULL
    AND created_at >= DATEADD(week, -8, GETDATE())
    AND lower(coalesce(utm_source,'')) = 'practo'
    AND phone_no IS NOT NULL AND phone_no <> ''
),
booked AS (   -- Practo phones that later booked a Screening Call → clinic is knowable
  SELECT DISTINCT RIGHT(regexp_replace(pat.phone_no,'[^0-9]',''),10) AS ph10
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id = t.id AND t.name = 'Screening Call' AND t.deleted_at IS NULL
  JOIN allo_persons.patient pat ON a.patient_id = pat.id AND pat.deleted_at IS NULL
  WHERE a.deleted_at IS NULL
    AND a.start_time >= DATEADD(week, -10, GETDATE())
)
SELECT
  count(*)                                                        AS practo_leads_8w,
  sum(CASE WHEN b.ph10 IS NOT NULL THEN 1 ELSE 0 END)            AS clinic_recoverable_via_booking,
  sum(CASE WHEN b.ph10 IS NULL THEN 1 ELSE 0 END)               AS unattributable,
  round(100.0 * sum(CASE WHEN b.ph10 IS NULL THEN 1 ELSE 0 END) / count(*), 1) AS pct_unattributable
FROM practo p
LEFT JOIN booked b ON b.ph10 = p.ph10;
-- Reading: 'unattributable' are Practo leads we can never place on a clinic
--   because they never booked AND the lead row has no clinic signal.  Even the
--   'recoverable' ones inherit the booking clinic, not the Practo listing — so
--   FIX 1 (per-clinic signal at source) is still required for true source→clinic
--   attribution of Practo demand.
