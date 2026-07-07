#!/usr/bin/env python3
"""Build data_d2p_econ.json — DONE-DATE economics (L2 D2P, invoiced), per clinic × week.

"What this week's consults were worth" — the demand-team revenue view. Keyed on DONE date
(appointment start_time week), invoiced amount credited to the consult (NOT paid date). A consult
paid later still counts here the moment its invoice is raised — payment collection is cashflow's job.

Ported from the L2 D2P query (purchased/invoice side only — prescription-pricing CTEs dropped):
  done       = COMPLETED/RECONSULTED offline Screening Calls (appt count)
  purchased  = those whose encounter has an invoice > 0 (status not created/cancelled) — drives D2P%
  meds/test/therapy _val = invoice_items payable by type ('drug' / 'lab' / therapy type_ids)
  prod_val   = meds_val + test_val + therapy_val  → RPC-done = prod_val / done
Offline = location_id NOT IN the 2 telehealth UUIDs. Clinic key = doctor seat (block) city/locality.

Run (heavy — background): AWS_PROFILE=redshift-data python3 scripts/build_d2p_economics.py
"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
TELE = "'c7d8c9d2-f389-4e8f-a260-71110195b83f','ffe8d849-3099-48fe-a2df-e324c4befe56'"
THER = "'fe5b19b4-5961-4036-bc5f-fb1009a27d64','b4409f49-3c8c-11f1-98e1-028ca0e1d7cd'"
MONTHS_BACK = 13   # cover the master's ~53-week history

SQL = f"""
WITH current_range AS (SELECT DATE_TRUNC('month', DATEADD(month, -{MONTHS_BACK}, CURRENT_DATE)) AS start_range),
elig AS (
  SELECT enc.id AS encounter_id
  FROM allo_consultations.appointments ap
  JOIN allo_consultations.types typ ON ap.type_id=typ.id AND typ.deleted_at IS NULL
  JOIN allo_encounters.encounters enc ON enc.appointment_id=ap.id AND enc.deleted_at IS NULL
  JOIN current_range cr ON TRUE
  WHERE ap.deleted_at IS NULL AND ap.status IN ('COMPLETED','RECONSULTED')
    AND typ.name IN ('Screening Call','Follow Up','Report Reading','Patient Queries')
    AND ap.consultation_id IS NOT NULL AND ap.start_time + INTERVAL '5.5 hours' >= cr.start_range),
paperform_qa AS (   -- patient diagnosis category from merged-rx paperform (L2 taxonomy)
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
iib_d AS (SELECT inv.encounter_id, SUM(ii.payable_amount::FLOAT)/100 AS med_b FROM allo_billing.invoices inv
  JOIN allo_billing.invoice_items ii ON ii.invoice_id=inv.id AND ii.deleted_at IS NULL
  WHERE inv.deleted_at IS NULL AND inv.status NOT IN ('cancelled') AND ii.type='drug'
    AND inv.encounter_id IN (SELECT encounter_id FROM elig) GROUP BY inv.encounter_id),
iib_l AS (SELECT inv.encounter_id, SUM(ii.payable_amount::FLOAT)/100 AS test_b FROM allo_billing.invoices inv
  JOIN allo_billing.invoice_items ii ON ii.invoice_id=inv.id AND ii.deleted_at IS NULL
  WHERE inv.deleted_at IS NULL AND inv.status NOT IN ('cancelled') AND ii.type='lab'
    AND inv.encounter_id IN (SELECT encounter_id FROM elig) GROUP BY inv.encounter_id),
iib_t AS (SELECT inv.encounter_id, SUM(ii.payable_amount::FLOAT)/100 AS ther_b FROM allo_billing.invoices inv
  JOIN allo_billing.invoice_items ii ON ii.invoice_id=inv.id AND ii.deleted_at IS NULL
  WHERE inv.deleted_at IS NULL AND inv.status NOT IN ('cancelled') AND ii.type_id IN ({THER})
    AND inv.encounter_id IN (SELECT encounter_id FROM elig) GROUP BY inv.encounter_id),
cons_fee AS (SELECT c.id AS cons_id, MAX(ii.payable_amount::FLOAT/100) AS cons_amt
  FROM allo_consultations.consultations c
  JOIN allo_billing.invoice_items ii ON ii.id=c.invoice_item_id AND ii.deleted_at IS NULL AND ii.type='consultation'
  JOIN allo_billing.invoices inv ON inv.id=ii.invoice_id AND inv.deleted_at IS NULL AND inv.status NOT IN ('created','cancelled')
  WHERE c.deleted_at IS NULL GROUP BY c.id),
dl AS (SELECT DISTINCT DATE(ab.start_time+INTERVAL '5.5 hours') AS block_dt, ab.id AS block_id, ab.provider_id, loc.city, loc.locality
  FROM allo_consultations.appointment_block_type_maps abtm
  LEFT JOIN allo_consultations.appointment_blocks ab ON abtm.appointment_block_id=ab.id
  LEFT JOIN allo_health.locations loc ON abtm.offline_location_id=loc.id AND loc.deleted_at IS NULL
  WHERE abtm.deleted_at IS NULL AND ab.deleted_at IS NULL AND abtm.offline_location_id IS NOT NULL),
appt_level AS (
  SELECT ap.id AS ap_id,
    date_trunc('week', ap.start_time+INTERVAL '5.5 hours')::date AS week_start,
    COALESCE(dl.city,'Online') AS doc_city, COALESCE(dl.locality,'Online') AS doc_locality,
    COALESCE(pro.name,'—') AS doctor,
    COALESCE(pf.diag_cat,'oth') AS diagnosis,
    CASE WHEN typ.name='Screening Call' AND (CASE WHEN aploc.id IN ({TELE}) OR aploc.id IS NULL THEN 0 ELSE 1 END)=1 THEN 'offline_sc'
         WHEN typ.name='Screening Call' THEN 'online_sc' ELSE 'repeat' END AS segment,
    MAX(COALESCE(iid.med_pbl,0)) AS med_amt, MAX(COALESCE(iil.test_pbl,0)) AS test_amt, MAX(COALESCE(iit.ther_pbl,0)) AS ther_amt, MAX(COALESCE(cf.cons_amt,0)) AS cons_amt,
    MAX(COALESCE(iib_d.med_b,0)) AS pres_med_amt, MAX(COALESCE(iib_l.test_b,0)) AS pres_test_amt, MAX(COALESCE(iib_t.ther_b,0)) AS pres_ther_amt,
    CASE WHEN MAX(inv.inv_amt)>0 THEN 1 ELSE 0 END AS purchased_flag
  FROM allo_consultations.appointments ap JOIN current_range cr ON TRUE
  JOIN allo_consultations.types typ ON ap.type_id=typ.id AND typ.deleted_at IS NULL
  JOIN allo_persons.providers pro ON pro.id=ap.provider_id AND pro.deleted_at IS NULL
  LEFT JOIN allo_health.locations aploc ON aploc.id=ap.location_id AND aploc.deleted_at IS NULL
  LEFT JOIN allo_encounters.encounters enc ON enc.appointment_id=ap.id AND enc.deleted_at IS NULL
  LEFT JOIN paperform_qa pf ON pf.patient_id=ap.patient_id
  LEFT JOIN dl ON dl.provider_id=ap.provider_id AND dl.block_dt=DATE(ap.start_time+INTERVAL '5.5 hours') AND dl.block_id=ap.block_id
  LEFT JOIN invoice_data inv ON inv.encounter_id=enc.id
  LEFT JOIN iid ON iid.encounter_id=enc.id LEFT JOIN iil ON iil.encounter_id=enc.id LEFT JOIN iit ON iit.encounter_id=enc.id LEFT JOIN iib_d ON iib_d.encounter_id=enc.id LEFT JOIN iib_l ON iib_l.encounter_id=enc.id LEFT JOIN iib_t ON iib_t.encounter_id=enc.id LEFT JOIN cons_fee cf ON cf.cons_id=ap.consultation_id
  WHERE ap.deleted_at IS NULL AND ap.status IN ('COMPLETED','RECONSULTED')
    AND typ.name IN ('Screening Call','Follow Up','Report Reading','Patient Queries') AND ap.consultation_id IS NOT NULL
    AND ap.start_time+INTERVAL '5.5 hours' >= cr.start_range
  GROUP BY ap.id, date_trunc('week', ap.start_time+INTERVAL '5.5 hours')::date, COALESCE(dl.city,'Online'), COALESCE(dl.locality,'Online'), COALESCE(pro.name,'—'), COALESCE(pf.diag_cat,'oth'), typ.name, aploc.id)
SELECT doc_city, doc_locality, doctor, week_start, diagnosis,
  COUNT(CASE WHEN segment='offline_sc' THEN 1 END) AS done,
  SUM(CASE WHEN segment='offline_sc' AND purchased_flag=1 THEN 1 ELSE 0 END) AS purchased,
  ROUND(SUM(CASE WHEN segment='offline_sc' THEN med_amt  ELSE 0 END)) AS meds_val,
  ROUND(SUM(CASE WHEN segment='offline_sc' THEN test_amt ELSE 0 END)) AS test_val,
  ROUND(SUM(CASE WHEN segment='offline_sc' THEN ther_amt ELSE 0 END)) AS ther_val,
  ROUND(SUM(CASE WHEN segment='offline_sc' THEN cons_amt ELSE 0 END)) AS cons_val,
  ROUND(SUM(CASE WHEN segment='offline_sc' THEN pres_med_amt  ELSE 0 END)) AS pres_meds_val,
  ROUND(SUM(CASE WHEN segment='offline_sc' THEN pres_test_amt ELSE 0 END)) AS pres_test_val,
  ROUND(SUM(CASE WHEN segment='offline_sc' THEN pres_ther_amt ELSE 0 END)) AS pres_ther_val
FROM appt_level
WHERE week_start >= DATE_TRUNC('week', DATEADD(month, -{MONTHS_BACK}, CURRENT_DATE))::date AND segment='offline_sc'
GROUP BY 1,2,3,4,5 ORDER BY 1,2,3,4,5;
"""


def run(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("query failed:\n" + (p.stderr or "")[:800] + "\n"); sys.exit(1)
    return [ln.split("\t") for ln in p.stdout.strip().splitlines() if ln.strip()]


def main():
    rows = run(SQL)
    weeks = sorted({r[3] for r in rows})
    widx = {w: i for i, w in enumerate(weeks)}
    NW = len(weeks)
    FIELDS = ["done", "purchased", "meds_val", "test_val", "ther_val", "cons_val", "pres_meds_val", "pres_test_val", "pres_ther_val"]

    def blank():
        return {f: [0]*NW for f in FIELDS}

    clinics = {}
    for r in rows:
        city, loc, doctor, wk, cat = r[0], r[1], r[2], r[3], r[4]
        key = f"{city}|{loc}"
        i = widx[wk]
        vals = [int(float(x)) for x in r[5:14]]
        o = clinics.setdefault(key, blank())
        c = o.setdefault("by_cat", {}).setdefault(cat, blank())
        dd = o.setdefault("by_doctor", {}).setdefault(doctor, blank())
        ddc = dd.setdefault("cat_done", {}).setdefault(cat, [0]*NW)   # per-doctor per-category DONE (for doctor-level category-share)
        for f, v in zip(FIELDS, vals):
            o[f][i] += v          # clinic total
            c[f][i] += v          # per-category (sum over doctors)
            dd[f][i] += v         # per-doctor (sum over categories)
            if f == "done": ddc[i] += v

    out = {"_meta": {"weeks": weeks,
                     "source": "L2 D2P (invoiced) · DONE-date offline SC · what consults were worth",
                     "note": "Invoiced value credited to consult/done week (not paid date). prod_val=meds+test+therapy. RPC-done=prod_val/done. D2P%=purchased/done.",
                     "fields": FIELDS},
           "clinics": clinics}
    json.dump(out, open(os.path.join(ROOT, "data_d2p_econ.json"), "w"), separators=(",", ":"))

    vwk = "2026-06-22"
    def cs(city, f):
        return sum(o[f][widx[vwk]] for k, o in clinics.items() if k.split("|")[0] == city) if vwk in widx else 0
    print(f"data_d2p_econ.json · {len(clinics)} clinics · {NW} weeks ({weeks[0]}→{weeks[-1]})")
    print(f"\n── verify {vwk} (L2 D2P targets) ──")
    tgt = {"Bangalore": (242, 187, 635218), "Mumbai": (136, 116, 464871), "Pune": (133, 115, 393249),
           "Hyderabad": (105, 81, 273410), "Chennai": (101, 82, 250547)}
    for c, (d, p, v) in tgt.items():
        pv = cs(c, "meds_val")+cs(c, "test_val")+cs(c, "ther_val")
        print(f"  {c:11} done {cs(c,'done'):4} ({d})  purch {cs(c,'purchased'):4} ({p})  prod_val {pv:>9,} ({v:,})")


if __name__ == "__main__":
    main()
