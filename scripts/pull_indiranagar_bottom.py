#!/usr/bin/env python3
"""Exact bottom-funnel for Bangalore|Indiranagar → data_indiranagar_bottom.json.

Per week (Monday, newest-first, 12 weeks) × diagnosis category, from Redshift:
  booked  = Screening Calls scheduled at the clinic that week (all statuses)
  done    = those that reached COMPLETED
  purchased = completed SCs that have a paid invoice (allo_billing.invoices status='paid')
  revenue = ₹ from those paid invoices

Category = the consultation's diagnosis tag (allo_analytics.encounter_tags, tag_category='diagnosis'):
  STI / ED+ / PE+ / ED+PE+ / NSSD / oth — same taxonomy as the clinic revenue pull.
NOTE: a diagnosis only exists once a patient is consulted, so booked-but-no-show SCs have no
category — they land in 'oth' for the booked count. done/purchased/revenue categories are exact.
Run:  AWS_PROFILE=redshift-data python3 scripts/pull_indiranagar_bottom.py
"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04",
         "2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23"]
idx = {w: i for i, w in enumerate(WEEKS)}; NW = len(WEEKS)
CATS = ["STI", "SH", "Other"]   # simplified: all ED/PE diagnoses roll up to Sexual Health
COLLAPSE = {"STI": "STI", "ED+": "SH", "PE+": "SH", "ED+PE+": "SH", "NSSD": "Other", "oth": "Other"}

SQL = """WITH loc AS (
    SELECT id FROM allo_health.locations
    WHERE deleted_at IS NULL AND city='Bangalore' AND locality='Indiranagar'),
  diag AS (
    SELECT e.appointment_id ap_id,
      CASE
        WHEN MAX(CASE WHEN et.tag_type='sti'             THEN 1 ELSE 0 END)=1 THEN 'STI'
        WHEN MAX(CASE WHEN et.tag_type='ed_plus_pe_plus' THEN 1 ELSE 0 END)=1 THEN 'ED+PE+'
        WHEN MAX(CASE WHEN et.tag_type='ed_plus'         THEN 1 ELSE 0 END)=1 THEN 'ED+'
        WHEN MAX(CASE WHEN et.tag_type='pe_plus'         THEN 1 ELSE 0 END)=1 THEN 'PE+'
        WHEN MAX(CASE WHEN et.tag_type='nssd'            THEN 1 ELSE 0 END)=1 THEN 'NSSD'
        ELSE 'oth' END diag_cat
    FROM allo_encounters.encounters e
    LEFT JOIN allo_analytics.encounter_tags et ON et.encounter_id=e.id AND et.tag_category='diagnosis' AND et.deleted_at IS NULL
    WHERE e.deleted_at IS NULL GROUP BY 1),
  ap0 AS (
    SELECT a.id, a.patient_id, a.start_time,
           TO_CHAR(DATE_TRUNC('week', a.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk,
           a.status,
           -- 1 when the patient's originating lead was created the SAME week as this booking
           CASE WHEN DATE_TRUNC('week', l.created_at + INTERVAL '5 hours 30 minutes')
                   = DATE_TRUNC('week', a.start_time + INTERVAL '5 hours 30 minutes') THEN 1 ELSE 0 END AS from_wk_lead
    FROM allo_consultations.appointments a
    JOIN allo_consultations.types typ ON typ.id=a.type_id AND typ.name='Screening Call'
    JOIN loc l2 ON l2.id=a.location_id
    LEFT JOIN allo_persons.patient p ON p.id=a.patient_id
    LEFT JOIN allo_persons.lead l ON l.id=p.lead_id
    WHERE a.start_time >= '2026-03-23' AND a.start_time < '2026-06-15' AND a.deleted_at IS NULL),
  ap AS (   -- DEDUPE to UNIQUE patient booking per week: reschedules / multiple SCs collapse to 1
    SELECT id, wk, status, from_wk_lead FROM (
      SELECT ap0.*, ROW_NUMBER() OVER (PARTITION BY patient_id, wk
        ORDER BY (CASE WHEN status='COMPLETED' THEN 0 ELSE 1 END), start_time) rn
      FROM ap0) z WHERE rn=1),
  inv AS (
    SELECT e.appointment_id ap_id, SUM(i.amount) amt
    FROM allo_encounters.encounters e
    JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.deleted_at IS NULL AND i.status='paid'
    WHERE e.deleted_at IS NULL GROUP BY 1)
  SELECT ap.wk, COALESCE(diag.diag_cat,'oth') cat,
    COUNT(*) booked,
    SUM(CASE WHEN ap.status='COMPLETED' THEN 1 ELSE 0 END) done,
    COUNT(CASE WHEN ap.status='COMPLETED' AND inv.ap_id IS NOT NULL THEN 1 END) purchased,
    SUM(CASE WHEN ap.status='COMPLETED' THEN COALESCE(inv.amt,0) ELSE 0 END) rev_paise,
    SUM(ap.from_wk_lead) booked_wk_lead,
    SUM(CASE WHEN ap.status='COMPLETED' AND ap.from_wk_lead=1 THEN 1 ELSE 0 END) done_wk_lead,
    COUNT(CASE WHEN ap.status='COMPLETED' AND inv.ap_id IS NOT NULL AND ap.from_wk_lead=1 THEN 1 END) purchased_wk_lead,
    SUM(CASE WHEN ap.status='COMPLETED' AND ap.from_wk_lead=1 THEN COALESCE(inv.amt,0) ELSE 0 END) rev_wk_lead_paise
  FROM ap LEFT JOIN diag ON diag.ap_id=ap.id LEFT JOIN inv ON inv.ap_id=ap.id
  GROUP BY 1,2 ORDER BY 1,2;"""

def main():
    p = subprocess.run([sys.executable, RQ], input=SQL, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("indiranagar bottom query failed: " + (p.stderr or "")[:400] + "\n"); sys.exit(1)
    FIELDS = ("booked","done","purchased","rev","booked_wk_lead","done_wk_lead","purchased_wk_lead","rev_wk_lead")
    def blank(): return {k: [0]*NW for k in FIELDS}
    bycat = {ct: blank() for ct in CATS}; tot = blank()
    for line in p.stdout.strip().splitlines():
        c = line.split("\t")
        if len(c) < 10: continue
        wk, cat = c[0], COLLAPSE.get(c[1], "Other")
        if wk not in idx: continue
        i = idx[wk]
        try:
            bk, dn, pu, rp, bwl, dwl, pwl, rwlp = (int(c[2]), int(c[3]), int(c[4]), int(float(c[5])),
                                                   int(c[6]), int(c[7]), int(c[8]), int(float(c[9])))
        except ValueError: continue
        rev = round(rp/100.0); rev_wl = round(rwlp/100.0)
        for tgt in (bycat[cat], tot):
            tgt["booked"][i]+=bk; tgt["done"][i]+=dn; tgt["purchased"][i]+=pu; tgt["rev"][i]+=rev
            tgt["booked_wk_lead"][i]+=bwl; tgt["done_wk_lead"][i]+=dwl
            tgt["purchased_wk_lead"][i]+=pwl; tgt["rev_wk_lead"][i]+=rev_wl
    out = {"_meta": {"weeks": WEEKS, "clinic": "Bangalore|Indiranagar", "cats": CATS,
            "source": "allo_consultations.appointments (Screening Call) × encounter diagnosis tag × paid invoices, clinic-filtered",
            "note": "booked=UNIQUE patient SC per week (reschedules / multiple SCs deduped, prefer the completed row); done=COMPLETED; purchased=completed+paid invoice; rev=₹ paid. Category=consultation diagnosis simplified to STI / SH (all ED·PE) / Other (only consulted SCs have one)."},
        "total": tot, "by_cat": bycat}
    json.dump(out, open(os.path.join(ROOT, "data_indiranagar_bottom.json"), "w"), separators=(",", ":"))
    print(f"wrote data_indiranagar_bottom.json")
    print(f"  latest wk: booked {tot['booked'][0]} done {tot['done'][0]} purchased {tot['purchased'][0]} rev ₹{tot['rev'][0]:,}")
    print("  by cat (latest done): " + " · ".join(f"{ct} {bycat[ct]['done'][0]}" for ct in CATS if bycat[ct]['done'][0]))

if __name__ == "__main__":
    main()
