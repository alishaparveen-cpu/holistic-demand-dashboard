-- Prescribed→Purchase per line (meds/tests/therapy), OFFLINE SC, per clinic (doctor's block) + doctor, weekly.
-- Prescription CTEs verbatim from the org's L2 query; final SELECT simplified to weekly line counts.
WITH current_range AS (SELECT DATE_TRUNC('month', DATEADD(month, -3, CURRENT_DATE)) AS start_range),
eligible_encounters AS (
    SELECT enc.id AS encounter_id, ap.id AS appointment_id
    FROM allo_consultations.appointments ap
    JOIN allo_consultations.types typ ON ap.type_id = typ.id AND typ.deleted_at IS NULL
    JOIN allo_encounters.encounters enc ON enc.appointment_id = ap.id AND enc.deleted_at IS NULL
    JOIN current_range cr ON TRUE
    WHERE ap.deleted_at IS NULL AND ap.status IN ('COMPLETED','RECONSULTED')
      AND typ.name IN ('Screening Call','Follow Up','Report Reading','Patient Queries')
      AND ap.consultation_id IS NOT NULL AND ap.start_time + INTERVAL '5.5 hours' >= cr.start_range),
prescription_data_drugs AS (
    SELECT drug_id, encounter_id,
        CASE WHEN COALESCE(pack_size,0)=0 THEN SUM(act_pres_med)
             ELSE CEIL(SUM(act_pres_med)::FLOAT / pack_size) * pack_size END AS pres_med_qty,
        ROW_NUMBER() OVER (PARTITION BY encounter_id ORDER BY encounter_id, drug_id) AS ron
    FROM (
        SELECT dor.drug_id, dor.encounter_id, di.pack_size,
            CASE WHEN dor.dispense IS NULL AND dor.frequency IN ('  ','as_needed','daily') THEN dor.duration::int
                 WHEN dor.dispense IS NULL AND dor.frequency = 'alternate_day'  THEN dor.duration::int / 2
                 WHEN dor.dispense IS NULL AND dor.frequency = 'once_in_3_days' THEN dor.duration::int / 3
                 WHEN dor.dispense IS NULL AND dor.frequency = 'once_a_week'    THEN dor.duration::int / 7
                 ELSE dor.dispense END AS act_pres_med
        FROM allo_drugs.orders dor
        LEFT JOIN allo_drugs.inventory di ON di.id = dor.drug_id AND di.deleted_at IS NULL
        WHERE dor.deleted_at IS NULL AND dor.encounter_id IN (SELECT encounter_id FROM eligible_encounters)
    ) s GROUP BY drug_id, encounter_id, pack_size),
prescription_data_labs AS (
    SELECT lor.lab_test_id, lor.encounter_id,
        ROW_NUMBER() OVER (PARTITION BY lor.encounter_id ORDER BY lor.encounter_id, lor.lab_test_id) AS ron0
    FROM allo_labs.orders lor
    WHERE lor.deleted_at IS NULL AND lor.encounter_id IN (SELECT encounter_id FROM eligible_encounters)),
prescription_data_therapy AS (
    SELECT encounter_id, consultation_id, quantity,
        ROW_NUMBER() OVER (PARTITION BY encounter_id ORDER BY encounter_id, quantity) AS ron1
    FROM allo_consultations.orders
    WHERE deleted_at IS NULL
      AND consultation_id IN ('fe5b19b4-5961-4036-bc5f-fb1009a27d64','b4409f49-3c8c-11f1-98e1-028ca0e1d7cd')
      AND encounter_id IN (SELECT encounter_id FROM eligible_encounters)),
rn_union AS (
    SELECT encounter_id, ron AS rn FROM prescription_data_drugs
    UNION SELECT encounter_id, ron0 FROM prescription_data_labs
    UNION SELECT encounter_id, ron1 FROM prescription_data_therapy),
prescription_data AS (
    SELECT en.id AS en_id, d.drug_id, d.pres_med_qty, l.lab_test_id, t.quantity, t.consultation_id AS therapy_type_id
    FROM allo_encounters.encounters en
    JOIN rn_union u ON u.encounter_id = en.id
    LEFT JOIN prescription_data_drugs   d ON d.encounter_id = en.id AND d.ron  = u.rn
    LEFT JOIN prescription_data_labs    l ON l.encounter_id = en.id AND l.ron0 = u.rn
    LEFT JOIN prescription_data_therapy t ON t.encounter_id = en.id AND t.ron1 = u.rn
    WHERE en.deleted_at IS NULL),
invoice_data AS (
    SELECT encounter_id, SUM(payable_amount::FLOAT)/100 AS inv_amt FROM allo_billing.invoices
    WHERE deleted_at IS NULL AND status NOT IN ('created','cancelled') AND encounter_id IN (SELECT encounter_id FROM eligible_encounters)
    GROUP BY encounter_id HAVING SUM(payable_amount::FLOAT)/100 > 0),
invoice_items_drug AS (
    SELECT inv.encounter_id, SUM(ii.payable_amount::FLOAT)/100 AS med_pbl
    FROM allo_billing.invoices inv JOIN allo_billing.invoice_items ii ON ii.invoice_id = inv.id AND ii.deleted_at IS NULL
    WHERE inv.deleted_at IS NULL AND inv.status NOT IN ('created','cancelled') AND ii.type = 'drug'
      AND inv.encounter_id IN (SELECT encounter_id FROM eligible_encounters) GROUP BY inv.encounter_id),
invoice_items_lab AS (
    SELECT inv.encounter_id, SUM(ii.payable_amount::FLOAT)/100 AS test_pbl
    FROM allo_billing.invoices inv JOIN allo_billing.invoice_items ii ON ii.invoice_id = inv.id AND ii.deleted_at IS NULL
    WHERE inv.deleted_at IS NULL AND inv.status NOT IN ('created','cancelled') AND ii.type = 'lab'
      AND inv.encounter_id IN (SELECT encounter_id FROM eligible_encounters) GROUP BY inv.encounter_id),
invoice_items_therapy AS (
    SELECT inv.encounter_id, SUM(ii.payable_amount::FLOAT)/100 AS ther_pbl
    FROM allo_billing.invoices inv JOIN allo_billing.invoice_items ii ON ii.invoice_id = inv.id AND ii.deleted_at IS NULL
    WHERE inv.deleted_at IS NULL AND inv.status NOT IN ('created','cancelled')
      AND ii.type_id IN ('fe5b19b4-5961-4036-bc5f-fb1009a27d64','b4409f49-3c8c-11f1-98e1-028ca0e1d7cd')
      AND inv.encounter_id IN (SELECT encounter_id FROM eligible_encounters) GROUP BY inv.encounter_id),
doctor_location AS (
    SELECT DISTINCT DATE(ab.start_time + INTERVAL '5.5 hours') AS block_dt, ab.id AS block_id, ab.provider_id, loc.city, loc.locality
    FROM allo_consultations.appointment_block_type_maps abtm
    LEFT JOIN allo_consultations.appointment_blocks ab ON abtm.appointment_block_id = ab.id
    LEFT JOIN allo_health.locations loc ON abtm.offline_location_id = loc.id AND loc.deleted_at IS NULL
    WHERE abtm.deleted_at IS NULL AND ab.deleted_at IS NULL AND abtm.offline_location_id IS NOT NULL),
appt_level AS (
    SELECT ap.id AS ap_id, DATE(ap.start_time + INTERVAL '5.5 hours') AS appt_dt,
        pro.name AS provider_name, COALESCE(dl.city,'Online') AS doc_city, COALESCE(dl.locality,'Online') AS doc_locality,
        CASE WHEN typ.name='Screening Call' AND (CASE WHEN aploc.id IN ('c7d8c9d2-f389-4e8f-a260-71110195b83f','ffe8d849-3099-48fe-a2df-e324c4befe56') OR aploc.id IS NULL THEN 0 ELSE 1 END)=1 THEN 'offline_sc'
             WHEN typ.name='Screening Call' THEN 'online_sc' ELSE 'repeat' END AS segment,
        MAX(CASE WHEN pres.drug_id IS NOT NULL THEN 1 ELSE 0 END) AS pres_drug_flag,
        MAX(CASE WHEN pres.lab_test_id IS NOT NULL THEN 1 ELSE 0 END) AS pres_test_flag,
        MAX(CASE WHEN pres.therapy_type_id IS NOT NULL THEN 1 ELSE 0 END) AS pres_therapy_flag,
        MAX(COALESCE(iid.med_pbl,0)) AS purch_med_amt, MAX(COALESCE(iil.test_pbl,0)) AS purch_test_amt, MAX(COALESCE(iit.ther_pbl,0)) AS purch_therapy_amt,
        CASE WHEN MAX(inv.inv_amt) > 0 THEN 1 ELSE 0 END AS purchased_flag
    FROM allo_consultations.appointments ap JOIN current_range cr ON TRUE
    JOIN allo_consultations.types typ ON ap.type_id = typ.id AND typ.deleted_at IS NULL
    JOIN allo_persons.providers pro ON pro.id = ap.provider_id AND pro.deleted_at IS NULL
    LEFT JOIN allo_health.locations aploc ON aploc.id = ap.location_id AND aploc.deleted_at IS NULL
    LEFT JOIN allo_encounters.encounters enc ON enc.appointment_id = ap.id AND enc.deleted_at IS NULL
    LEFT JOIN doctor_location dl ON dl.provider_id = ap.provider_id AND dl.block_dt = DATE(ap.start_time + INTERVAL '5.5 hours') AND dl.block_id = ap.block_id
    LEFT JOIN prescription_data pres ON pres.en_id = enc.id
    LEFT JOIN invoice_data inv ON inv.encounter_id = enc.id
    LEFT JOIN invoice_items_drug iid ON iid.encounter_id = enc.id
    LEFT JOIN invoice_items_lab iil ON iil.encounter_id = enc.id
    LEFT JOIN invoice_items_therapy iit ON iit.encounter_id = enc.id
    WHERE ap.deleted_at IS NULL AND ap.status IN ('COMPLETED','RECONSULTED')
      AND typ.name IN ('Screening Call','Follow Up','Report Reading','Patient Queries') AND ap.consultation_id IS NOT NULL
      AND ap.start_time + INTERVAL '5.5 hours' >= cr.start_range
    GROUP BY ap.id, DATE(ap.start_time + INTERVAL '5.5 hours'), pro.name, COALESCE(dl.city,'Online'), COALESCE(dl.locality,'Online'), typ.name, aploc.id)
SELECT doc_city, doc_locality, provider_name, date_trunc('week', appt_dt)::date AS week_start,
    SUM(CASE WHEN segment='offline_sc' AND pres_drug_flag=1 THEN 1 ELSE 0 END) AS meds_pres,
    SUM(CASE WHEN segment='offline_sc' AND purch_med_amt>0 THEN 1 ELSE 0 END) AS meds_purch,
    SUM(CASE WHEN segment='offline_sc' AND pres_test_flag=1 THEN 1 ELSE 0 END) AS test_pres,
    SUM(CASE WHEN segment='offline_sc' AND purch_test_amt>0 THEN 1 ELSE 0 END) AS test_purch,
    SUM(CASE WHEN segment='offline_sc' AND pres_therapy_flag=1 THEN 1 ELSE 0 END) AS ther_pres,
    SUM(CASE WHEN segment='offline_sc' AND purch_therapy_amt>0 THEN 1 ELSE 0 END) AS ther_purch,
    SUM(CASE WHEN segment='offline_sc' AND (pres_drug_flag=1 OR pres_test_flag=1 OR pres_therapy_flag=1) THEN 1 ELSE 0 END) AS any_pres,
    SUM(CASE WHEN segment='offline_sc' AND (purch_med_amt>0 OR purch_test_amt>0 OR purch_therapy_amt>0) THEN 1 ELSE 0 END) AS any_purch
FROM appt_level WHERE segment='offline_sc'
GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;
