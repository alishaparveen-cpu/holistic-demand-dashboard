#!/usr/bin/env python3
"""Build data_leads.json — per clinic/week offline leads split by source bucket
(gmb, google_ad, organic, fb, justdial, others) from production.public.main_source_wise_leads.
Keyed "City|Clinic", arrays newest-first aligned to the diagnostic's 12 Monday-weeks.
Practo is excluded here (external feed; lives in data_practo_leads.json).
Run: python3 scripts/build_leads.py   (needs AWS SSO / IAM)"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKS=["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23"]
idx = {w:i for i,w in enumerate(WEEKS)}; NW = len(WEEKS)
CHANS = ["gmb","google_ad","organic","fb","justdial","others","practo_crm","outbound_wa"]
# fetch_leads.sql column order: city, clinic, wk_mon, google_ad, gmb, organic, fb, justdial, others, practo_crm, outbound_wa, total
COLS = ["google_ad","gmb","organic","fb","justdial","others","practo_crm","outbound_wa"]
sql = open(os.path.join(ROOT,"scripts","fetch_leads.sql")).read()
p = subprocess.run([sys.executable, os.path.join(ROOT,"scripts","redshift_query.py")],
                   input=sql, capture_output=True, text=True)
if p.returncode != 0 or "ERROR" in p.stderr:
    sys.stderr.write("fetch_leads.sql failed: "+(p.stderr or "")[:300]+"\n"); sys.exit(1)
D = {}
for line in p.stdout.strip().splitlines():
    c = line.split("\t")
    if len(c) < 11: continue
    city, clinic, wk = c[0], c[1], c[2]
    if wk not in idx: continue
    o = D.setdefault(f"{city}|{clinic}", {ch:[0]*NW for ch in CHANS})
    for j, col in enumerate(COLS):
        try: o[col][idx[wk]] += int(float(c[3+j]))
        except (ValueError, IndexError): pass
out = {"_meta":{"source":"production.public.main_source_wise_leads (Redshift, hourly)",
                "weeks":WEEKS, "fields":"gmb=listing clicks+inbound calls · google_ad=paid · organic · fb=Meta · justdial · others"}}
out.update(D)
json.dump(out, open(os.path.join(ROOT,"data_leads.json"),"w"), separators=(",",":"))
print(f"data_leads.json · {len(D)} clinics")
b = D.get("Bangalore|Bellandur")
if b: print("Bellandur wk0 — gmb:", b["gmb"][0], "google_ad:", b["google_ad"][0], "organic:", b["organic"][0])
