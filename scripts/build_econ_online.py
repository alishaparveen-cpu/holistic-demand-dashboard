#!/usr/bin/env python3
"""Build data_d2p_econ_online.json + data_fu_econ_online.json — DONE-date economics for ONLINE consults.

Same L2 D2P (invoiced) logic as the offline econ builders, but segments the appt_level by ONLINE:
  online_sc  = Screening Call, telehealth (aploc IN TELE or NULL)   → data_d2p_econ_online.json
  fu_online  = Follow Up,      telehealth (aploc IN TELE or NULL)   → data_fu_econ_online.json
Online has no physical clinic → single national key 'Online|Online', depth via by_cat / by_doctor.
One shared query (the appt_level scan is the expensive part). Run (heavy, background):
  AWS_PROFILE=redshift-data python3 scripts/build_econ_online.py
"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
TELE = "'c7d8c9d2-f389-4e8f-a260-71110195b83f','ffe8d849-3099-48fe-a2df-e324c4befe56'"
THER = "'fe5b19b4-5961-4036-bc5f-fb1009a27d64','b4409f49-3c8c-11f1-98e1-028ca0e1d7cd'"
MONTHS_BACK = 13

SQL = f"""
WITH current_range AS (SELECT DATE_TRUNC('month', DATEADD(month, -{MONTHS_BACK}, CURRENT_DATE)) AS start_range),
doctor_location AS (
  SELECT DISTINCT DATE(ab.start_time + INTERVAL '5.5 hours') AS block_dt, ab.id AS block_id, ab.provider_id, loc.city, loc.locality
  FROM allo_consultations.appointment_block_type_maps abtm
  LEFT JOIN allo_consultations.appointment_blocks ab ON abtm.appointment_block_id=ab.id
  LEFT JOIN allo_health.locations loc ON abtm.offline_location_id=loc.id AND loc.deleted_at IS NULL
  WHERE abtm.deleted_at IS NULL AND ab.deleted_at IS NULL AND abtm.offline_location_id IS NOT NULL),
elig AS (
  SELECT enc.id AS encounter_id
  FROM allo_consultations.appointments ap
  JOIN allo_consultations.types typ ON ap.type_id=typ.id AND typ.deleted_at IS NULL
  JOIN allo_encounters.encounters enc ON enc.appointment_id=ap.id AND enc.deleted_at IS NULL
  JOIN current_range cr ON TRUE
  WHERE ap.deleted_at IS NULL AND ap.status IN ('COMPLETED','RECONSULTED')
    AND typ.name IN ('Screening Call','Follow Up','Report Reading','Patient Queries')
    AND ap.consultation_id IS NOT NULL AND ap.start_time + INTERVAL '5.5 hours' >= cr.start_range),
paperform_qa AS (
  SELECT b.patient_id,
    CASE WHEN b.diagnosis ILIKE '%Mental Health Concern%' THEN 'MH'
      WHEN b.diagnosis ILIKE '%Genito Urinary Infection%' OR b.diagnosis ILIKE '%GUI%' OR b.diagnosis ILIKE '%Post-Exposure%' THEN 'STI'
      WHEN b.diagnosis ILIKE '%Premature Ejaculation%' AND b.diagnosis ILIKE '%Erectile Dysfunction%' THEN 'ED+PE+'
      WHEN b.diagnosis ILIKE '%Erectile Dysfunction%' THEN 'ED+'
      WHEN b.diagnosis ILIKE '%Premature Ejaculation%' THEN 'PE+'
      WHEN b.diagnosis ILIKE '%Low Sexual Desire%' THEN 'LSD'
      WHEN b.diagnosis ILIKE '%Delayed Ejaculation%' THEN 'DE'
      WHEN b.diagnosis ILIKE '%Dyspareunia%' OR b.diagnosis ILIKE '%Pain during sex%' THEN 'DYS'
      WHEN b.diagnosis ILIKE '%Porn Addiction%' THEN 'PA'
      WHEN b.diagnosis ILIKE '%Compulsive Masturbation%' THEN 'CM'
      WHEN b.diagnosis ILIKE '%Vaginismus%' THEN 'VGS'
      WHEN b.diagnosis ILIKE '%Female Sexual Arousal Disorder%' THEN 'FSAD'
      WHEN b.diagnosis ILIKE '%Anorgasmia%' THEN 'AORG'
      WHEN b.diagnosis ILIKE '%Not Otherwise Specified%' THEN 'NOS' ELSE 'oth' END AS diag_cat
  FROM (SELECT enc.patient_id, LISTAGG(pqa.value, ',') AS diagnosis,
          RANK() OVER (PARTITION BY enc.patient_id ORDER BY enc.created_at DESC) AS rnk
        FROM allo_encounters.encounters enc
        LEFT JOIN allo_health.paperform_qa pqa ON pqa.encounter_id=enc.id AND pqa.deleted_at IS NULL AND pqa.title ILIKE '%diagnosis%'
        WHERE enc.deleted_at IS NULL AND LOWER(enc.type) LIKE '%merged-rx%'
        GROUP BY enc.patient_id, enc.created_at) b WHERE rnk=1),
invoice_data AS (SELECT encounter_id, SUM(payable_amount::FLOAT)/100 AS inv_amt FROM allo_billing.invoices
  WHERE deleted_at IS NULL AND status NOT IN ('created','cancelled') AND encounter_id IN (SELECT encounter_id FROM elig)
  GROUP BY encounter_id HAVING SUM(payable_amount::FLOAT)/100>0),
iid AS (SELECT inv.encounter_id, SUM(ii.payable_amount::FLOAT)/100 AS med_pbl FROM allo_billing.invoices inv
  JOIN allo_billing.invoice_items ii ON ii.invoice_id=inv.id AND ii.deleted_at IS NULL
  WHERE inv.deleted_at IS NULL AND inv.status NOT IN ('created','cancelled') AND ii.type='drug'
    AND inv.encounter_id IN (SELECT encounter_id FROM elig) GROUP BY inv.encounter_id),
iil AS (SELECT inv.encounter_id, SUM(ii.payable_amount::FLOAT)/100 AS test_pbl FROM allo_billing.invoices inv
  JOIN allo_billing.invoice_items ii ON ii.invoice_id=inv.id AND ii.deleted_at IS NULL
  WHERE inv.deleted_at IS NULL AND inv.status NOT IN ('created','cancelled') AND ii.type='lab'
    AND inv.encounter_id IN (SELECT encounter_id FROM elig) GROUP BY inv.encounter_id),
iit AS (SELECT inv.encounter_id, SUM(ii.payable_amount::FLOAT)/100 AS ther_pbl FROM allo_billing.invoices inv
  JOIN allo_billing.invoice_items ii ON ii.invoice_id=inv.id AND ii.deleted_at IS NULL
  WHERE inv.deleted_at IS NULL AND inv.status NOT IN ('created','cancelled') AND ii.type_id IN ({THER})
    AND inv.encounter_id IN (SELECT encounter_id FROM elig) GROUP BY inv.encounter_id),
cons_fee AS (SELECT c.id AS cons_id, MAX(ii.payable_amount::FLOAT/100) AS cons_amt
  FROM allo_consultations.consultations c
  JOIN allo_billing.invoice_items ii ON ii.id=c.invoice_item_id AND ii.deleted_at IS NULL AND ii.type='consultation'
  JOIN allo_billing.invoices inv ON inv.id=ii.invoice_id AND inv.deleted_at IS NULL AND inv.status NOT IN ('created','cancelled')
  WHERE c.deleted_at IS NULL GROUP BY c.id),
po_drug AS (SELECT DISTINCT encounter_id FROM allo_drugs.orders WHERE deleted_at IS NULL AND encounter_id IN (SELECT encounter_id FROM elig)),
po_lab  AS (SELECT DISTINCT encounter_id FROM allo_labs.orders  WHERE deleted_at IS NULL AND encounter_id IN (SELECT encounter_id FROM elig)),
po_ther AS (SELECT DISTINCT encounter_id FROM allo_consultations.orders WHERE deleted_at IS NULL AND consultation_id IN ('fe5b19b4-5961-4036-bc5f-fb1009a27d64','b4409f49-3c8c-11f1-98e1-028ca0e1d7cd') AND encounter_id IN (SELECT encounter_id FROM elig)),
appt_level AS (
  SELECT ap.id AS ap_id,
    date_trunc('week', ap.start_time+INTERVAL '5.5 hours')::date AS week_start,
    COALESCE(pro.name,'—') AS doctor,
    COALESCE(dl.city,'Online') AS city, COALESCE(dl.locality,'Online') AS locality,
    COALESCE(pf.diag_cat,'oth') AS diagnosis,
    CASE WHEN typ.name='Screening Call' THEN 'online_sc'
         WHEN typ.name='Follow Up'      THEN 'fu_online'
         ELSE 'other' END AS segment,
    MAX(COALESCE(iid.med_pbl,0)) AS med_amt, MAX(COALESCE(iil.test_pbl,0)) AS test_amt, MAX(COALESCE(iit.ther_pbl,0)) AS ther_amt, MAX(COALESCE(cf.cons_amt,0)) AS cons_amt,
    CASE WHEN MAX(inv.inv_amt)>0 THEN 1 ELSE 0 END AS purchased_flag,
    MAX(CASE WHEN pod.encounter_id IS NOT NULL THEN 1 ELSE 0 END) AS pres_drug_flag,
    MAX(CASE WHEN pol.encounter_id IS NOT NULL THEN 1 ELSE 0 END) AS pres_lab_flag,
    MAX(CASE WHEN pot.encounter_id IS NOT NULL THEN 1 ELSE 0 END) AS pres_ther_flag
  FROM allo_consultations.appointments ap JOIN current_range cr ON TRUE
  JOIN allo_consultations.types typ ON ap.type_id=typ.id AND typ.deleted_at IS NULL
  JOIN allo_persons.providers pro ON pro.id=ap.provider_id AND pro.deleted_at IS NULL
  LEFT JOIN allo_health.locations aploc ON aploc.id=ap.location_id AND aploc.deleted_at IS NULL
  LEFT JOIN doctor_location dl ON ap.provider_id=dl.provider_id AND DATE(ap.start_time+INTERVAL '5.5 hours')=dl.block_dt AND ap.block_id=dl.block_id
  LEFT JOIN allo_encounters.encounters enc ON enc.appointment_id=ap.id AND enc.deleted_at IS NULL
  LEFT JOIN paperform_qa pf ON pf.patient_id=ap.patient_id
  LEFT JOIN invoice_data inv ON inv.encounter_id=enc.id
  LEFT JOIN iid ON iid.encounter_id=enc.id LEFT JOIN iil ON iil.encounter_id=enc.id LEFT JOIN iit ON iit.encounter_id=enc.id LEFT JOIN cons_fee cf ON cf.cons_id=ap.consultation_id
  LEFT JOIN po_drug pod ON pod.encounter_id=enc.id LEFT JOIN po_lab pol ON pol.encounter_id=enc.id LEFT JOIN po_ther pot ON pot.encounter_id=enc.id
  WHERE ap.deleted_at IS NULL AND ap.status IN ('COMPLETED','RECONSULTED')
    AND typ.name IN ('Screening Call','Follow Up') AND ap.consultation_id IS NOT NULL
    AND ap.location_id IN ({TELE})   -- ONLINE = the 2 telehealth location UUIDs (sheet definition; name-match undercounted per city)
    AND ap.start_time+INTERVAL '5.5 hours' >= cr.start_range
  GROUP BY ap.id, date_trunc('week', ap.start_time+INTERVAL '5.5 hours')::date, COALESCE(pro.name,'—'), COALESCE(dl.city,'Online'), COALESCE(dl.locality,'Online'), COALESCE(pf.diag_cat,'oth'), typ.name, aploc.id)
SELECT segment, city, locality, doctor, week_start, diagnosis,
  COUNT(*) AS done,
  SUM(purchased_flag) AS purchased,
  ROUND(SUM(med_amt)) AS meds_val, ROUND(SUM(test_amt)) AS test_val, ROUND(SUM(ther_amt)) AS ther_val, ROUND(SUM(cons_amt)) AS cons_val,
  SUM(pres_drug_flag) AS meds_pres_cnt, SUM(pres_lab_flag) AS test_pres_cnt, SUM(pres_ther_flag) AS ther_pres_cnt,
  SUM(CASE WHEN med_amt>0 THEN 1 ELSE 0 END) AS meds_purch_cnt, SUM(CASE WHEN test_amt>0 THEN 1 ELSE 0 END) AS test_purch_cnt, SUM(CASE WHEN ther_amt>0 THEN 1 ELSE 0 END) AS ther_purch_cnt
FROM appt_level
WHERE week_start >= DATE_TRUNC('week', DATEADD(month, -{MONTHS_BACK}, CURRENT_DATE))::date AND segment IN ('online_sc','fu_online')
GROUP BY 1,2,3,4,5,6 ORDER BY 1,2,3,4,5,6;
"""


def run(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("query failed:\n" + (p.stderr or "")[:800] + "\n"); sys.exit(1)
    return [ln.split("\t") for ln in p.stdout.strip().splitlines() if ln.strip()]


def build(rows, seg, weeks):
    widx = {w: i for i, w in enumerate(weeks)}
    NW = len(weeks)
    FIELDS = ["done", "purchased", "meds_val", "test_val", "ther_val", "cons_val", "meds_pres_cnt", "test_pres_cnt", "ther_pres_cnt", "meds_purch_cnt", "test_purch_cnt", "ther_purch_cnt"]
    blank = lambda: {f: [0]*NW for f in FIELDS}
    KEY = "Online|Online"
    clinics = {}
    for r in rows:
        if r[0] != seg:
            continue
        city, loc, doctor, wk, cat = r[1], r[2], r[3], r[4], r[5]
        key = city + "|" + loc
        i = widx[wk]
        vals = [int(float(x)) for x in r[6:18]]
        o = clinics.setdefault(key, blank())
        c = o.setdefault("by_cat", {}).setdefault(cat, blank())
        dd = o.setdefault("by_doctor", {}).setdefault(doctor, blank())
        for f, v in zip(FIELDS, vals):
            o[f][i] += v; c[f][i] += v; dd[f][i] += v
    return clinics


def main():
    rows = run(SQL)
    weeks = sorted({r[4] for r in rows})
    NW = len(weeks)
    for seg, fname, label in [("online_sc", "data_d2p_econ_online.json", "L2 D2P (invoiced) · DONE-date ONLINE Screening Call"),
                              ("fu_online", "data_fu_econ_online.json", "L2 D2P (invoiced) · DONE-date ONLINE Follow-Up")]:
        clinics = build(rows, seg, weeks)
        out = {"_meta": {"weeks": weeks, "source": label,
                         "note": "Per-clinic online (city|locality via doctor's block that day); unresolved → 'Online|Online'. by_cat / by_doctor depth. Invoiced value at done week.",
                         "fields": ["done", "purchased", "meds_val", "test_val", "ther_val", "cons_val", "meds_pres_cnt", "test_pres_cnt", "ther_pres_cnt", "meds_purch_cnt", "test_purch_cnt", "ther_purch_cnt"]},
               "clinics": clinics}
        json.dump(out, open(os.path.join(ROOT, fname), "w"), separators=(",", ":"))
        tot_done = sum(sum(o["done"]) for o in clinics.values())
        nat_done = sum(clinics.get("Online|Online", {}).get("done", [0]))
        print(f"{fname} · {len(clinics)} clinic-keys · {NW} weeks · total done {tot_done} · unresolved {nat_done} ({100*nat_done//max(1,tot_done)}%)")


if __name__ == "__main__":
    main()
