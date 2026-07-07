#!/usr/bin/env python3
"""Build data_paid_rev.json — PAID-DATE revenue (cash collected), per clinic × week × channel.

The L2 "Revenue query" — actual payments (allo_health.payments), keyed on paid date, attributed to the
doctor's seat location, split by channel: New Offline (SC offline) / New Online / Repeat (FU/RR/PQ) /
Direct Purchase / Other. This is the cash-flow view — pairs with the done-week invoiced revenue.

master2 maps: SC funnel → New Offline · FU funnel → Repeat · Combined → all channels.
Run (heavy, background): AWS_PROFILE=redshift-data python3 scripts/build_paid_revenue.py
"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
TELE = "'c7d8c9d2-f389-4e8f-a260-71110195b83f','ffe8d849-3099-48fe-a2df-e324c4befe56'"
THER = "'fe5b19b4-5961-4036-bc5f-fb1009a27d64','b4409f49-3c8c-11f1-98e1-028ca0e1d7cd'"
MONTHS = 13

SQL = f"""
WITH doctor_location AS (
  SELECT ab.id AS block_id, MAX(loc.city) AS doc_city, MAX(loc.locality) AS doc_locality
  FROM allo_consultations.appointment_block_type_maps abtm
  JOIN allo_consultations.appointment_blocks ab ON abtm.appointment_block_id=ab.id
  JOIN allo_health.locations loc ON abtm.offline_location_id=loc.id AND loc.deleted_at IS NULL
  WHERE abtm.deleted_at IS NULL AND ab.deleted_at IS NULL GROUP BY ab.id ),
cons_appt AS (
  SELECT consultation_id, block_id, ap_pro, ap_loc, ap_type, loc_type FROM (
    SELECT ap1.consultation_id, ap1.block_id, ap1.provider_id ap_pro, ap1.location_id ap_loc, t.name ap_type, lc.type AS loc_type,
      ROW_NUMBER() OVER (PARTITION BY ap1.consultation_id ORDER BY ap1.created_at DESC) rn
    FROM allo_consultations.appointments ap1
    LEFT JOIN allo_consultations.types t ON ap1.type_id=t.id
    LEFT JOIN allo_health.locations lc ON lc.id=ap1.location_id
    WHERE ap1.deleted_at IS NULL AND ap1.consultation_id IS NOT NULL
      AND ap1.created_at + INTERVAL '5.5 hours' >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '{MONTHS+3} month'
  ) WHERE rn=1 ),
cii AS (SELECT invoice_id, item_id FROM (
    SELECT invoice_id, id AS item_id, ROW_NUMBER() OVER (PARTITION BY invoice_id ORDER BY payable_amount DESC) rn
    FROM allo_billing.invoice_items WHERE type='consultation' AND payable_amount>0 AND type_id <> 'fe5b19b4-5961-4036-bc5f-fb1009a27d64'
  ) WHERE rn=1 ),
cons_link AS (SELECT item_id, cons_id, patient_id FROM (
    SELECT invoice_item_id AS item_id, id AS cons_id, patient_id, ROW_NUMBER() OVER (PARTITION BY invoice_item_id ORDER BY created_at) rn
    FROM allo_consultations.consultations WHERE deleted_at IS NULL AND invoice_item_id IS NOT NULL ) WHERE rn=1 )
SELECT
  date_trunc('week', p.created_at + INTERVAL '5.5 hours')::date AS wk,
  COALESCE(dle.doc_city, dlc.doc_city, al.city, l_enc.city, l_cons.city, 'Online') AS city,
  COALESCE(dle.doc_locality, dlc.doc_locality, al.locality, l_enc.locality, l_cons.locality, 'Online') AS locality,
  CASE WHEN p.invoice_id IS NULL THEN 'no_invoice'
    WHEN e.id IS NULL AND cl.cons_id IS NULL THEN 'Direct'
    WHEN (CASE WHEN e.id IS NOT NULL AND e.appointment_id IS NULL THEN 'Report Reading' ELSE COALESCE(t_enc.name, ca.ap_type) END)='Screening Call'
      AND COALESCE(enc_loc.type, ca.loc_type)='offline' THEN 'New Offline'
    WHEN (CASE WHEN e.id IS NOT NULL AND e.appointment_id IS NULL THEN 'Report Reading' ELSE COALESCE(t_enc.name, ca.ap_type) END)='Screening Call' THEN 'New Online'
    WHEN (CASE WHEN e.id IS NOT NULL AND e.appointment_id IS NULL THEN 'Report Reading' ELSE COALESCE(t_enc.name, ca.ap_type) END) IN ('Follow Up','Patient Queries','Report Reading') THEN 'Repeat'
    ELSE 'Other' END AS channel,
  ROUND(SUM(p.amount)/100) AS rev
FROM allo_health.payments p
  LEFT JOIN allo_billing.invoices i ON p.invoice_id=i.id AND i.deleted_at IS NULL
  LEFT JOIN allo_encounters.encounters e ON i.encounter_id=e.id AND e.deleted_at IS NULL
  LEFT JOIN allo_consultations.appointments app ON e.appointment_id=app.id AND app.deleted_at IS NULL
  LEFT JOIN allo_consultations.types t_enc ON app.type_id=t_enc.id
  LEFT JOIN allo_health.locations enc_loc ON enc_loc.id=app.location_id
  LEFT JOIN allo_health.locations al ON al.id=app.location_id
  LEFT JOIN cii ON cii.invoice_id=p.invoice_id
  LEFT JOIN cons_link cl ON cl.item_id=cii.item_id
  LEFT JOIN cons_appt ca ON ca.consultation_id=cl.cons_id
  LEFT JOIN allo_persons.patient pe ON e.patient_id=pe.id
  LEFT JOIN allo_persons.patient pc ON COALESCE(cl.patient_id, i.user_id)=pc.id
  LEFT JOIN allo_health.locations l_enc ON COALESCE(pe.onboarding_location_id, app.location_id)=l_enc.id
  LEFT JOIN allo_health.locations l_cons ON COALESCE(pc.onboarding_location_id, ca.ap_loc)=l_cons.id
  LEFT JOIN doctor_location dle ON app.block_id=dle.block_id
  LEFT JOIN doctor_location dlc ON ca.block_id=dlc.block_id
WHERE p.deleted_at IS NULL
  AND date_trunc('week', p.created_at + INTERVAL '5.5 hours')::date >= DATE_TRUNC('week', DATEADD(month,-{MONTHS},CURRENT_DATE))::date
  AND COALESCE(p.razorpay_payment_id,'') NOT IN ('pay_Pi8fEI4UXiZH7B','pay_PjC9cYgU2QAUlO','pay_Pk6h5GNdahPpEh','pay_PmT7hIwUCifk4d','pay_PmgpgJHc1cKiRG')
  AND COALESCE(p.razorpay_payment_id,'') NOT IN (SELECT DISTINCT id FROM allo_vendors.razorpay_payments WHERE notes LIKE '%name%' AND notes LIKE '%email%' AND notes LIKE '%phone%')
GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;
"""


def run(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("query failed:\n" + (p.stderr or "")[:800] + "\n"); sys.exit(1)
    return [ln.split("\t") for ln in p.stdout.strip().splitlines() if ln.strip()]


def main():
    rows = run(SQL)
    weeks = sorted({r[0] for r in rows})
    widx = {w: i for i, w in enumerate(weeks)}
    NW = len(weeks)
    CH = ["New Offline", "New Online", "Repeat", "Direct", "Other", "no_invoice"]
    clinics = {}
    for r in rows:
        wk, city, loc, ch, rev = r[0], r[1], r[2], r[3], int(float(r[4]))
        key = f"{city}|{loc}"
        o = clinics.setdefault(key, {c: [0]*NW for c in CH})
        if ch in o:
            o[ch][widx[wk]] += rev
    out = {"_meta": {"weeks": weeks, "channels": CH,
                     "source": "L2 Revenue query · payments · PAID date · doctor-seat location · by channel",
                     "note": "SC→'New Offline', FU→'Repeat', Combined→all. Pairs with done-week invoiced revenue."},
           "clinics": clinics}
    json.dump(out, open(os.path.join(ROOT, "data_paid_rev.json"), "w"), separators=(",", ":"))
    vwk = "2026-06-22"
    if vwk in widx:
        j = widx[vwk]
        tot = {c: sum(o[c][j] for o in clinics.values()) for c in CH}
        print(f"data_paid_rev.json · {len(clinics)} clinics · {NW} weeks ({weeks[0]}→{weeks[-1]})")
        print(f"── paid rev {vwk} by channel ──")
        for c in CH:
            print(f"  {c:12} ₹{tot[c]:,}")
        print(f"  TOTAL        ₹{sum(tot.values()):,}   (New Offline≈SC · Repeat≈FU)")


if __name__ == "__main__":
    main()
