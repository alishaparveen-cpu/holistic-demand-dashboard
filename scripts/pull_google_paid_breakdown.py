#!/usr/bin/env python3
"""Clean Google-paid breakdown — decode the campaign-name convention into stable
axes instead of 40+ noisy raw campaigns. Source: production.public.af_filled_users
(current, has utm_source/medium/campaign + patient_id), joined to bookings_data_raw
for the booked outcome.

Axes (all decoded from utm_campaign / utm_medium):
  mechanism  : WEB (landing page) vs CALL (number on the ad → tracking/pool #)
  brand      : Brand vs Generic
  intent     : Online (online consult) vs Local (clinic/offline) vs Other
  category   : ED / PE / STI / SH / Sexology / Other

Writes data_google_paid.json (12-wk aggregate + per-axis cuts, leads & booked).
Run: AWS_PROFILE=redshift-data python3 scripts/pull_google_paid_breakdown.py
"""
import os, sys, subprocess, json, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
START = "2026-03-23"   # 12 weeks

SQL = f"""
WITH g AS (
  SELECT DISTINCT patient_id,
    COALESCE(utm_campaign,'') AS camp, COALESCE(utm_medium,'') AS med
  FROM production.public.af_filled_users
  WHERE dt >= '{START}' AND LOWER(utm_source)='google' AND patient_id IS NOT NULL
),
bk AS (SELECT DISTINCT patient_id FROM production.public.bookings_data_raw WHERE phone_rank=1)
SELECT g.camp, g.med, CASE WHEN bk.patient_id IS NOT NULL THEN 1 ELSE 0 END AS booked, COUNT(*) n
FROM g LEFT JOIN bk ON bk.patient_id=g.patient_id
GROUP BY 1,2,3;
"""

p = subprocess.run([sys.executable, os.path.join(ROOT,"scripts","redshift_query.py")],
                   input=SQL, capture_output=True, text=True)
if p.returncode != 0 or "ERROR" in (p.stderr or ""):
    sys.stderr.write("query failed: "+(p.stderr or "")[:400]+"\n"); sys.exit(1)

def classify(camp, med):
    c = camp.lower()
    mech = "CALL" if re.fullmatch(r"[0-9]{6,}", med) else "WEB"
    brand = "Brand" if "brand" in c else "Generic"
    if "online" in c or c.startswith("onl_") or "_onl_" in c: intent = "Online"
    elif "local" in c or "offline" in c or c.startswith("t1_") or "_lc" in c or c.endswith("_lc"): intent = "Local"
    else: intent = "Other"
    if re.search(r"(^|_)ed(_|$)|erectile", c): cat = "ED"
    elif re.search(r"(^|_)pe(_|$)", c): cat = "PE"
    elif re.search(r"std|sti", c): cat = "STI"
    elif "sexolog" in c or "sexdoctor" in c or "sexology" in c: cat = "Sexology"
    elif re.search(r"(^|_)sh(_|$)|sexual", c): cat = "SH"
    else: cat = "Other"
    return mech, brand, intent, cat

# accumulate {axis_value: [leads, booked]}
def acc():
    return {}
def add(d, k, n, b):
    o = d.setdefault(k, [0,0]); o[0]+=n; o[1]+=b

by_mech, by_brand, by_intent, by_cat, total = acc(), acc(), acc(), acc(), [0,0]
combo = acc()  # brand|intent|cat|mech for the full cube
for line in p.stdout.strip().splitlines():
    parts = line.split("\t")
    if len(parts) < 4: continue
    camp, med, booked, n = parts[0], parts[1], int(parts[2]), int(float(parts[3]))
    mech, brand, intent, cat = classify(camp, med)
    total[0]+=n; total[1]+=booked*n
    add(by_mech, mech, n, booked*n); add(by_brand, brand, n, booked*n)
    add(by_intent, intent, n, booked*n); add(by_cat, cat, n, booked*n)
    add(combo, f"{brand}|{intent}|{cat}|{mech}", n, booked*n)

def pct(o): return round(100*o[1]/o[0],1) if o[0] else 0
out = {"_meta":{"source":"af_filled_users (utm_source=google) × bookings_data_raw","window":f"{START}..now (12 wks)",
                "note":"Google-paid leads decoded from campaign names. booked = patient ever booked (phone_rank=1)."},
       "total":{"leads":total[0],"booked":total[1],"book_pct":pct(total)}}
for name, d in [("by_mechanism",by_mech),("by_brand",by_brand),("by_intent",by_intent),("by_category",by_cat)]:
    out[name] = {k:{"leads":v[0],"booked":v[1],"book_pct":pct(v)} for k,v in sorted(d.items(), key=lambda x:-x[1][0])}
out["cube"] = {k:{"leads":v[0],"booked":v[1],"book_pct":pct(v)} for k,v in sorted(combo.items(), key=lambda x:-x[1][0])}
json.dump(out, open(os.path.join(ROOT,"data_google_paid.json"),"w"), indent=1)

# ---- print a readable summary ----
print(f"TOTAL Google paid: {total[0]} leads → {total[1]} booked ({pct(total)}%)\n")
for title, d in [("MECHANISM",by_mech),("BRAND",by_brand),("INTENT (online/local)",by_intent),("CATEGORY",by_cat)]:
    print(f"— {title} —")
    for k,v in sorted(d.items(), key=lambda x:-x[1][0]):
        print(f"   {k:10} {v[0]:5} leads → {v[1]:4} booked  ({pct(v)}%)")
    print()
print("— TOP CUBE CELLS (brand|intent|cat|mech) —")
for k,v in sorted(combo.items(), key=lambda x:-x[1][0])[:12]:
    print(f"   {k:34} {v[0]:5} → {v[1]:4} ({pct(v)}%)")
