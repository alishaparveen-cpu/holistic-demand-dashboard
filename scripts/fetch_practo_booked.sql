-- TRUE Practo bookings: every Screening-Call appointment with its patient phone, clinic & booking week.
-- We match patient phone against the Practo sheet's lead phones in Python → a booking counts as Practo
-- if the patient first came in via Practo (captures phone follow-up, not just Practo's online slot-booking).
SELECT l.city, l.locality AS clinic,
    TO_CHAR(DATE_TRUNC('week', DATE(a.start_time + INTERVAL '5.5 hours')),'YYYY-MM-DD') AS wk,
    p.phone_no
FROM allo_consultations.appointments a
    JOIN allo_consultations.consultations c ON a.consultation_id = c.id
    JOIN allo_health.locations l ON a.location_id = l.id
    JOIN allo_persons.patient p ON c.patient_id = p.id
WHERE a.deleted_at IS NULL AND c.deleted_at IS NULL AND l.deleted_at IS NULL
    AND c.consultation_type_id = (SELECT id FROM allo_consultations.types WHERE name = 'Screening Call')
    AND DATE(a.start_time + INTERVAL '5.5 hours') BETWEEN '2026-03-16' AND '2026-06-07'
    AND p.phone_no IS NOT NULL AND p.phone_no <> ''
