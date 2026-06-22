#!/usr/bin/env python3
"""Exact bottom-funnel for Pune|Hadapsar → data_hadapsar_bottom.json.

Per week (Monday, newest-first, 13 weeks) × diagnosis category, from Redshift:
  booked   = Screening Calls scheduled at the Hadapsar clinic (Savali_Allo_Clinic) that week
  done     = those that reached COMPLETED
  purchased = completed SCs with a paid invoice
  revenue  = ₹ from paid invoices

Category = STI / SH (ED+/PE+/ED+PE+ combined) / MH / Other.
Run: AWS_PROFILE=redshift-data python3 scripts/pull_hadapsar_bottom.py
"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11",
         "2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]
idx = {w: i for i, w in enumerate(WEEKS)}; NW = len(WEEKS)
CATS = ["STI", "SH", "MH", "Other"]
# MH is now derived from allo_observations.diagnoses (ICD-11 6A–6E codes + keywords)
# for 'oth' appointments (no STI/SH encounter tag). STI/SH still from encounter_tags.

SQL = """WITH loc AS (
    SELECT id FROM allo_health.locations
    WHERE deleted_at IS NULL AND city='Pune' AND locality='Hadapsar'),
  enc_tag AS (
    SELECT e.appointment_id ap_id,
      CASE
        WHEN MAX(CASE WHEN et.tag_type='sti'             THEN 1 ELSE 0 END)=1 THEN 'STI'
        WHEN MAX(CASE WHEN et.tag_type='ed_plus_pe_plus' THEN 1 ELSE 0 END)=1 THEN 'ED+PE+'
        WHEN MAX(CASE WHEN et.tag_type='ed_plus'         THEN 1 ELSE 0 END)=1 THEN 'ED+'
        WHEN MAX(CASE WHEN et.tag_type='pe_plus'         THEN 1 ELSE 0 END)=1 THEN 'PE+'
        WHEN MAX(CASE WHEN et.tag_type='nssd'            THEN 1 ELSE 0 END)=1 THEN 'NSSD'
        ELSE 'oth' END tag_cat
    FROM allo_encounters.encounters e
    LEFT JOIN allo_analytics.encounter_tags et ON et.encounter_id=e.id AND et.tag_category='diagnosis' AND et.deleted_at IS NULL
    WHERE e.deleted_at IS NULL GROUP BY 1),
  mh_ap AS (
    SELECT DISTINCT e.appointment_id ap_id
    FROM allo_encounters.encounters e
    JOIN allo_observations.diagnoses d ON d.encounter_id=e.id AND d.deleted_at IS NULL
    WHERE e.deleted_at IS NULL
      AND (d.description LIKE '%(6A%' OR d.description LIKE '%(6B%'
           OR d.description LIKE '%(6C%' OR d.description LIKE '%(6D%'
           OR d.description LIKE '%(6E%'
           OR d.description ILIKE '%anxiety%' OR d.description ILIKE '%depress%'
           OR d.description ILIKE '%adhd%'    OR d.description ILIKE '%psychosis%'
           OR d.description ILIKE '%bipolar%' OR d.description ILIKE '%personality%'
           OR d.description ILIKE '%nicotine%' OR d.description ILIKE '%addiction%'
           OR d.description ILIKE '%adjustment%' OR d.description ILIKE '%ptsd%')),
  ap0 AS (
    SELECT a.id, a.patient_id,
           TO_CHAR(DATE_TRUNC('week', a.created_at + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk,
           a.status
    FROM allo_consultations.appointments a
    JOIN allo_consultations.types typ ON typ.id=a.type_id AND typ.name='Screening Call'
    JOIN loc l2 ON l2.id=a.location_id
    WHERE a.created_at >= '2026-03-16' AND a.deleted_at IS NULL),
  ap AS (
    SELECT id, wk, status FROM (
      SELECT ap0.*, ROW_NUMBER() OVER (PARTITION BY patient_id, wk
        ORDER BY (CASE WHEN status='COMPLETED' THEN 0 ELSE 1 END), id) rn
      FROM ap0) z WHERE rn=1),
  inv AS (
    SELECT e.appointment_id ap_id, SUM(i.amount) amt
    FROM allo_encounters.encounters e
    JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.deleted_at IS NULL AND i.status='paid'
    WHERE e.deleted_at IS NULL GROUP BY 1)
  SELECT ap.wk,
    CASE
      WHEN COALESCE(et.tag_cat,'oth')='STI'                        THEN 'STI'
      WHEN COALESCE(et.tag_cat,'oth') IN ('ED+','PE+','ED+PE+','NSSD') THEN 'SH'
      WHEN COALESCE(et.tag_cat,'oth')='oth' AND mh.ap_id IS NOT NULL  THEN 'MH'
      ELSE 'Other'
    END cat,
    COUNT(*) booked,
    SUM(CASE WHEN ap.status='COMPLETED' THEN 1 ELSE 0 END) done,
    COUNT(CASE WHEN ap.status='COMPLETED' AND inv.ap_id IS NOT NULL THEN 1 END) purchased,
    SUM(CASE WHEN ap.status='COMPLETED' THEN COALESCE(inv.amt,0) ELSE 0 END) rev_paise
  FROM ap
  LEFT JOIN enc_tag et ON et.ap_id=ap.id
  LEFT JOIN mh_ap mh ON mh.ap_id=ap.id
  LEFT JOIN inv ON inv.ap_id=ap.id
  GROUP BY 1,2 ORDER BY 1,2;"""

def main():
    p = subprocess.run([sys.executable, RQ], input=SQL, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("hadapsar bottom query failed: " + (p.stderr or "")[:400] + "\n"); sys.exit(1)
    FIELDS = ("booked","done","purchased","rev")
    def blank(): return {k: [0]*NW for k in FIELDS}
    bycat = {ct: blank() for ct in CATS}; tot = blank()
    for line in p.stdout.strip().splitlines():
        c = line.split("\t")
        if len(c) < 6: continue
        wk, cat = c[0], c[1]
        if cat not in CATS: cat = "Other"
        if wk not in idx: continue
        i = idx[wk]
        try: bk, dn, pu, rp = int(c[2]), int(c[3]), int(c[4]), int(float(c[5]))
        except ValueError: continue
        rev = round(rp/100.0)
        for tgt in (bycat[cat], tot):
            tgt["booked"][i] += bk; tgt["done"][i] += dn
            tgt["purchased"][i] += pu; tgt["rev"][i] += rev
    out = {"_meta": {"weeks": WEEKS, "clinic": "Pune|Hadapsar", "cats": CATS,
            "source": "allo_consultations.appointments (Screening Call) × encounter_tags (STI/SH) × allo_observations.diagnoses (MH via ICD-11) × paid invoices",
            "note": "Hadapsar clinic = Savali_Allo_Clinic. booked=unique patient SC per week; done=COMPLETED; rev=₹. STI/SH via encounter_tags; MH via ICD-11 coded diagnoses (6A–6E) or MH keywords on appointments with no STI/SH tag."},
        "total": tot, "by_cat": bycat}
    json.dump(out, open(os.path.join(ROOT, "data_hadapsar_bottom.json"), "w"), separators=(",", ":"))
    print(f"wrote data_hadapsar_bottom.json")
    print(f"  latest wk: booked {tot['booked'][0]} done {tot['done'][0]} purchased {tot['purchased'][0]} rev ₹{tot['rev'][0]:,}")
    print("  by cat (done): " + " · ".join(f"{ct} {bycat[ct]['done'][0]}" for ct in CATS))

if __name__ == "__main__":
    main()
