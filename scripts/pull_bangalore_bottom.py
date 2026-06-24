#!/usr/bin/env python3
"""Bottom funnel (booked / done / purchased / revenue) for ALL Bangalore clinics,
per clinic AND city total — so the clinic funnels provably SUM to the city.
Same definitions as pull_indiranagar_bottom.py:
  booked = UNIQUE patient Screening Call per (clinic, week) — reschedules/multiple SCs deduped (prefer COMPLETED)
  done = COMPLETED · purchased = completed + paid invoice · rev = ₹ paid
  category = consultation diagnosis (STI / SH=all ED·PE / Other) — only consulted SCs have one
Writes data_bangalore_bottom.json {weeks, clinics{clinic{total,by_cat}}, city{total,by_cat}}.
Run: AWS_PROFILE=redshift-data python3 scripts/pull_bangalore_bottom.py
"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11",
         "2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]
idx = {w: i for i, w in enumerate(WEEKS)}; NW = len(WEEKS)
CATS = ["STI", "SH", "Other"]
COLLAPSE = {"STI":"STI","ED+":"SH","PE+":"SH","ED+PE+":"SH","NSSD":"Other","oth":"Other"}

SQL = """WITH loc AS (
    SELECT id, locality FROM allo_health.locations
    WHERE deleted_at IS NULL AND city='Bangalore'),
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
    SELECT a.id, a.patient_id, a.start_time, loc.locality AS clinic,
           TO_CHAR(DATE_TRUNC('week', a.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk,
           a.status
    FROM allo_consultations.appointments a
    JOIN allo_consultations.types typ ON typ.id=a.type_id AND typ.name='Screening Call'
    JOIN loc ON loc.id=a.location_id
    WHERE a.start_time >= '2026-03-30' AND a.start_time < '2026-06-22' AND a.deleted_at IS NULL),
  ap AS (   -- DEDUPE to unique patient booking per clinic per week (reschedules collapse; prefer COMPLETED)
    SELECT id, clinic, wk, status FROM (
      SELECT ap0.*, ROW_NUMBER() OVER (PARTITION BY patient_id, clinic, wk
        ORDER BY (CASE WHEN status='COMPLETED' THEN 0 ELSE 1 END), start_time) rn
      FROM ap0) z WHERE rn=1),
  inv AS (
    SELECT e.appointment_id ap_id, SUM(i.amount) amt
    FROM allo_encounters.encounters e
    JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.deleted_at IS NULL AND i.status='paid'
    WHERE e.deleted_at IS NULL GROUP BY 1)
  SELECT ap.clinic, ap.wk, COALESCE(diag.diag_cat,'oth') cat,
    COUNT(*) booked,
    SUM(CASE WHEN ap.status='COMPLETED' THEN 1 ELSE 0 END) done,
    COUNT(CASE WHEN ap.status='COMPLETED' AND inv.ap_id IS NOT NULL THEN 1 END) purchased,
    SUM(CASE WHEN ap.status='COMPLETED' THEN COALESCE(inv.amt,0) ELSE 0 END) rev_paise
  FROM ap LEFT JOIN diag ON diag.ap_id=ap.id LEFT JOIN inv ON inv.ap_id=ap.id
  GROUP BY 1,2,3 ORDER BY 1,2;"""

p = subprocess.run([sys.executable, RQ], input=SQL, capture_output=True, text=True)
if p.returncode != 0 or "ERROR" in (p.stderr or ""):
    sys.stderr.write("bangalore bottom failed: " + (p.stderr or "")[:400] + "\n"); sys.exit(1)

FIELDS = ("booked", "done", "purchased", "rev")
def blank(): return {"total": {k: [0]*NW for k in FIELDS}, "by_cat": {c: {k: [0]*NW for k in FIELDS} for c in CATS}}
clinics = {}
for line in p.stdout.strip().splitlines():
    c = line.split("\t")
    if len(c) < 7: continue
    clinic, wk, rawcat = c[0], c[1], c[2]
    if wk not in idx: continue
    cat = COLLAPSE.get(rawcat, "Other"); i = idx[wk]
    try: bk, dn, pu, rp = int(c[3]), int(c[4]), int(c[5]), int(float(c[6]))
    except ValueError: continue
    rev = round(rp/100.0)
    o = clinics.setdefault(clinic, blank())
    for tgt in (o["total"], o["by_cat"][cat]):
        tgt["booked"][i]+=bk; tgt["done"][i]+=dn; tgt["purchased"][i]+=pu; tgt["rev"][i]+=rev

# city total = sum of clinics
city = blank()
for clinic, o in clinics.items():
    for k in FIELDS:
        for i in range(NW): city["total"][k][i] += o["total"][k][i]
        for cat in CATS:
            for i in range(NW): city["by_cat"][cat][k][i] += o["by_cat"][cat][k][i]

out = {"_meta": {"weeks": WEEKS, "city": "Bangalore", "cats": CATS,
        "source": "allo_consultations.appointments (Screening Call, deduped to unique patient/clinic/week) × diagnosis × paid invoices",
        "note": "Per clinic + city total (= sum of clinics). booked=unique patient SC/wk; done=COMPLETED; purchased=+paid; rev=₹."},
    "clinics": clinics, "city": city}
json.dump(out, open(os.path.join(ROOT, "data_bangalore_bottom.json"), "w"), separators=(",", ":"))

# reconciliation proof
chk = sum(clinics[c]["total"]["booked"][0] for c in clinics)
print(f"clinics: {len(clinics)}")
print(f"latest-wk city booked={city['total']['booked'][0]} done={city['total']['done'][0]} purchased={city['total']['purchased'][0]} rev=Rs{city['total']['rev'][0]:,}")
print(f"RECONCILE booked latest: sum of clinics = {chk}  vs  city = {city['total']['booked'][0]}  -> {'OK' if chk==city['total']['booked'][0] else 'MISMATCH'}")
print("Indiranagar latest booked (should match the clinic funnel ~46):", clinics.get("Indiranagar",{}).get("total",{}).get("booked",['?'])[0])
