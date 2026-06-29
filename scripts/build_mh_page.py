#!/usr/bin/env python3
"""Build data_mh.json for the combined MH page (mh.html).

For the 5 MH-focused clinics, weekly (Monday, newest-first, 12 wk ending 2026-06-15):
  bottom — booked/done/purchased/revenue × category (STI / SH / MH / Other)
           MH via allo_observations.diagnoses (ICD-11 6A-6E + keywords), same method
           as scripts/pull_hadapsar_bottom.py. STI/SH via encounter_tags.
  leads  — CRM leads by channel, from data_clinic_funnel.json (already per-clinic)
  gmb    — GMB insights (searches/calls/website/directions) from data_gmb_insights.json
  summary— per-clinic H1(wk1-6)→H2(wk7-12) MH vs SH deltas + cannibalisation verdict
Run: AWS_PROFILE=redshift-data python3 scripts/build_mh_page.py
"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11",
         "2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]
idx = {w: i for i, w in enumerate(WEEKS)}; NW = len(WEEKS)
CATS = ["STI", "SH", "MH", "Other"]
# clinic key (city|locality) → display name for the selector
CLINICS = [
    ("Coimbatore|Bharathi Nagar", "Bharathi Nagar · Coimbatore"),
    ("Bangalore|Indiranagar",     "Indiranagar · Bangalore"),
    ("Bangalore|KR Puram",        "KR Puram · Bangalore"),
    ("Pune|Hadapsar",             "Hadapsar · Pune"),
    ("Jaipur|Vaishali Nagar",     "Vaishali Nagar · Jaipur"),
]
PAIRS = " OR ".join("(city='%s' AND locality='%s')" % (k.split("|")[0].replace("'","''"),
                                                       k.split("|")[1].replace("'","''"))
                    for k, _ in CLINICS)

SQL = """WITH loc AS (
    SELECT id, city||'|'||locality clinic FROM allo_health.locations
    WHERE deleted_at IS NULL AND ({pairs})),
  enc_tag AS (
    SELECT e.appointment_id ap_id,
      CASE
        WHEN MAX(CASE WHEN et.tag_type='sti' THEN 1 ELSE 0 END)=1 THEN 'STI'
        WHEN MAX(CASE WHEN et.tag_type IN ('ed_plus_pe_plus','ed_plus','pe_plus','nssd') THEN 1 ELSE 0 END)=1 THEN 'SH'
        ELSE 'oth' END tag_cat
    FROM allo_encounters.encounters e
    LEFT JOIN allo_analytics.encounter_tags et ON et.encounter_id=e.id AND et.tag_category='diagnosis' AND et.deleted_at IS NULL
    WHERE e.deleted_at IS NULL GROUP BY 1),
  mh_ap AS (
    SELECT DISTINCT e.appointment_id ap_id
    FROM allo_encounters.encounters e
    JOIN allo_observations.diagnoses d ON d.encounter_id=e.id AND d.deleted_at IS NULL
    WHERE e.deleted_at IS NULL
      AND (d.description LIKE '%(6A%' OR d.description LIKE '%(6B%' OR d.description LIKE '%(6C%'
           OR d.description LIKE '%(6D%' OR d.description LIKE '%(6E%'
           OR d.description ILIKE '%anxiety%' OR d.description ILIKE '%depress%' OR d.description ILIKE '%adhd%'
           OR d.description ILIKE '%psychosis%' OR d.description ILIKE '%bipolar%' OR d.description ILIKE '%personality%'
           OR d.description ILIKE '%nicotine%' OR d.description ILIKE '%addiction%' OR d.description ILIKE '%adjustment%'
           OR d.description ILIKE '%ptsd%')),
  ap0 AS (
    SELECT a.id, a.patient_id, loc.clinic,
           TO_CHAR(DATE_TRUNC('week', a.created_at + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk, a.status
    FROM allo_consultations.appointments a
    JOIN allo_consultations.types typ ON typ.id=a.type_id AND typ.name='Screening Call'
    JOIN loc ON loc.id=a.location_id
    WHERE a.created_at >= '2026-03-30' AND a.created_at < '2026-06-29' AND a.deleted_at IS NULL),
  ap AS (
    SELECT id, clinic, wk, status FROM (
      SELECT ap0.*, ROW_NUMBER() OVER (PARTITION BY patient_id, clinic, wk
        ORDER BY (CASE WHEN status='COMPLETED' THEN 0 ELSE 1 END), id) rn FROM ap0) z WHERE rn=1),
  inv AS (
    SELECT e.appointment_id ap_id, SUM(i.amount) amt
    FROM allo_encounters.encounters e
    JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.deleted_at IS NULL AND i.status='paid'
    WHERE e.deleted_at IS NULL GROUP BY 1)
  SELECT ap.clinic, ap.wk,
    CASE WHEN COALESCE(et.tag_cat,'oth')='STI' THEN 'STI'
         WHEN COALESCE(et.tag_cat,'oth')='SH' THEN 'SH'
         WHEN mh.ap_id IS NOT NULL THEN 'MH' ELSE 'Other' END cat,
    COUNT(*) booked,
    SUM(CASE WHEN ap.status='COMPLETED' THEN 1 ELSE 0 END) done,
    COUNT(CASE WHEN ap.status='COMPLETED' AND inv.ap_id IS NOT NULL THEN 1 END) purchased,
    SUM(CASE WHEN ap.status='COMPLETED' THEN COALESCE(inv.amt,0) ELSE 0 END) rev_paise
  FROM ap LEFT JOIN enc_tag et ON et.ap_id=ap.id LEFT JOIN mh_ap mh ON mh.ap_id=ap.id
  LEFT JOIN inv ON inv.ap_id=ap.id
  GROUP BY 1,2,3 ORDER BY 1,2,3;""".format(pairs=PAIRS)

def L(f):
    try: return json.load(open(os.path.join(ROOT, f)))
    except Exception: return {}

def main():
    p = subprocess.run([sys.executable, RQ], input=SQL, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("mh bottom query failed: " + (p.stderr or "")[:500] + "\n"); sys.exit(1)

    FIELDS = ("booked", "done", "purchased", "rev")
    def blank(): return {k: [0]*NW for k in FIELDS}
    # clinic → {total, by_cat{cat:{fields}}}
    bottom = {k: {"total": blank(), "by_cat": {c: blank() for c in CATS}} for k, _ in CLINICS}
    for line in p.stdout.strip().splitlines():
        c = line.split("\t")
        if len(c) < 7: continue
        clinic, wk, cat = c[0], c[1], c[2]
        if clinic not in bottom or wk not in idx: continue
        if cat not in CATS: cat = "Other"
        i = idx[wk]
        try: bk, dn, pu, rp = int(c[3]), int(c[4]), int(c[5]), int(float(c[6]))
        except ValueError: continue
        rev = round(rp/100.0)
        for tgt in (bottom[clinic]["total"], bottom[clinic]["by_cat"][cat]):
            tgt["booked"][i]+=bk; tgt["done"][i]+=dn; tgt["purchased"][i]+=pu; tgt["rev"][i]+=rev

    cf  = (L("data_clinic_funnel.json") or {}).get("clinics", {})
    gmb_all = L("data_gmb_insights.json")
    Z = [0]*NW
    def pad(a): return (list(a or []) + Z)[:NW]

    clinics_out = {}
    summary = []
    for k, disp in CLINICS:
        lead = (cf.get(k, {}) or {}).get("lead", {}); bychan = lead.get("by_chan", {})
        bc = lambda key: pad(bychan.get(key))
        g = gmb_all.get(k, {})
        bot = bottom[k]
        clinics_out[k] = {
            "display": disp,
            "bottom": bot,
            "leads": {
                "total": pad(lead.get("leads_total")),
                "by_chan": {"gmb": bc("gmb"), "google_web": bc("google_ad"), "organic": bc("organic"),
                            "practo": bc("practo_crm"), "fb": bc("fb"),
                            "other": [bc("others")[i]+bc("justdial")[i] for i in range(NW)]},
                "gmb_call_volume": pad(lead.get("gmb_organic_calls")),
            },
            "gmb": {"impr": pad(g.get("searches")), "calls": pad(g.get("calls")),
                    "website": pad(g.get("website")), "directions": pad(g.get("directions"))},
        }
        # cannibalisation summary: H1 (wk index 6-11 = older half) vs H2 (index 0-5 = recent half)
        def half(arr): return sum(arr[6:]), sum(arr[:6])   # (older H1, recent H2)
        mh = bot["by_cat"]["MH"]["done"]; sh = bot["by_cat"]["SH"]["done"]
        mh1, mh2 = half(mh); sh1, sh2 = half(sh)
        t1, t2 = mh1+sh1, mh2+sh2
        dmh, dsh, dtot = mh2-mh1, sh2-sh1, t2-t1
        if dmh > 0 and dsh < 0 and dtot <= max(2, 0.15*t1) and dtot < dmh:
            verdict = "cannibalising"
        elif dmh > 0 and dsh >= 0:
            verdict = "additive"
        elif dmh <= 0:
            verdict = "mh_low"
        else:
            verdict = "mixed"
        summary.append({"clinic": k, "display": disp, "mh": [mh1, mh2], "sh": [sh1, sh2],
                        "total": [t1, t2], "dmh": dmh, "dsh": dsh, "dtot": dtot, "verdict": verdict})

    out = {"_meta": {"weeks": WEEKS, "cats": CATS, "clinics": [k for k, _ in CLINICS],
            "halves": {"H1": "wk of 30 Mar–4 May (older 6)", "H2": "wk of 11 May–15 Jun (recent 6)"},
            "source": "bottom: appointments(Screening Call)×encounter_tags(STI/SH)×observations.diagnoses(MH ICD-11)×paid invoices; leads: data_clinic_funnel; gmb: data_gmb_insights",
            "note": "booked=unique patient SC/clinic/week (created_at); MH = ICD-11 6A-6E / MH-keyword diagnosis on appointments with no STI/SH tag. Cannibalising = MH done up while SH down and total flat (MH substituting SH); additive = both up."},
        "clinics": clinics_out, "summary": summary}
    json.dump(out, open(os.path.join(ROOT, "data_mh.json"), "w"), separators=(",", ":"))
    print("wrote data_mh.json")
    for s in summary:
        print(f"  {s['display']:28s} MH {s['mh'][0]}->{s['mh'][1]} ({s['dmh']:+d})  SH {s['sh'][0]}->{s['sh'][1]} ({s['dsh']:+d})  [{s['verdict']}]")

if __name__ == "__main__":
    main()
