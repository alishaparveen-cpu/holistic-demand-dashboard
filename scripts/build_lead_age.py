#!/usr/bin/env python3
"""Build data_lead_age.json — per clinic, weekly split of bookings by the AGE of the lead that
produced them: same-week (fresh), last-week (1-wk lag), older (2+ wks backlog). Keyed City|Clinic,
arrays newest-first aligned to the diagnostic's 12 weeks. Run: python3 scripts/build_lead_age.py"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKS=["2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23"]
idx = {w:i for i,w in enumerate(WEEKS)}
sql = open(os.path.join(ROOT,"scripts","fetch_lead_age.sql")).read()
p = subprocess.run([sys.executable, os.path.join(ROOT,"scripts","redshift_query.py")],
                   input=sql, capture_output=True, text=True)
if p.returncode != 0 or "ERROR" in p.stderr:
    sys.stderr.write("fetch_lead_age.sql failed: "+(p.stderr or "")[:300]+"\n"); sys.exit(1)
D = {}
for line in p.stdout.strip().splitlines():
    c = line.split("\t")
    if len(c) < 5: continue
    city, clinic, wk, age, n = c[0], c[1], c[2], c[3], int(float(c[4]))
    if wk not in idx: continue
    key = f"{city}|{clinic}"
    o = D.setdefault(key, {"same":[0]*12, "last":[0]*12, "older":[0]*12})
    if age in o: o[age][idx[wk]] += n
out = {"_meta":{"source":"main_source_wise_leads — bookings by lead age (created_on → call_booking_ts)",
                "weeks":WEEKS, "fields":"same=lead booked same wk · last=1-wk lag · older=2+ wks backlog"}}
out.update(D)
json.dump(out, open(os.path.join(ROOT,"data_lead_age.json"),"w"), separators=(",",":"))
print(f"data_lead_age.json · {len(D)} clinics")
b = D.get("Bangalore|Bellandur")
if b: print("Bellandur wk0 — same:", b["same"][0], "last:", b["last"][0], "older:", b["older"][0])
