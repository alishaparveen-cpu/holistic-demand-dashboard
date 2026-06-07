#!/usr/bin/env python3
"""Build data_booking_source.json — per clinic/week, booked SC appts traced to lead channel
(via patient.lead_id -> lead.utm_source/origin/gclid) with outcome split. 12 Monday-weeks, newest-first."""
import json, os, subprocess, sys
HERE=os.path.dirname(__file__); RUN=os.path.join(HERE,'redshift_query.py'); ROOT=os.path.join(HERE,'..')
WEEKS=["2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20",
       "2026-04-13","2026-04-06","2026-03-30","2026-03-23","2026-03-16","2026-03-09"]
WI={w:i for i,w in enumerate(WEEKS)}
SUB=["total","done","missed","resched_patient","resched_clinic","resched_noshow","cancelled","scheduled"]
def q(f):
    sql=open(os.path.join(HERE,f)).read()
    p=subprocess.run([sys.executable,RUN],input=sql,capture_output=True,text=True)
    if p.returncode!=0: raise RuntimeError(p.stderr[-400:])
    return [l.split('\t') for l in p.stdout.splitlines() if l.strip()]
def num(x):
    try: return int(x)
    except: return 0
D={}
for c in q('fetch_booking_source.sql'):
    if len(c)<12: continue
    city,clinic,wk,ch=c[0],c[1],c[2],c[3]
    if wk not in WI: continue
    o=D.setdefault(f"{city}|{clinic}",{})
    seg=o.setdefault(ch,{f:[0]*12 for f in SUB})
    for j,f in enumerate(SUB): seg[f][WI[wk]]=num(c[4+j])
out={"_meta":{"weeks":WEEKS,
    "source":"appointments -> patient.lead_id -> lead.utm_source/origin/gclid (Screening Calls, offline clinics)",
    "note":"Per clinic/week: BOOKINGS split by acquisition channel, each with outcome counts. 99.95% of booked patients link to a lead; ~95% have utm_source. This is the source of bookings, NOT all leads (clinic-level lead-source for non-bookers is unavailable).",
    "channels":["Google Ads","Meta","Practo","Google Maps (GMB)","Organic","WhatsApp","Google organic","Other","Unknown","No lead record"]}}
out.update(D)
json.dump(out,open(os.path.join(ROOT,"data_booking_source.json"),"w"),separators=(",",":"))
b=D.get("Bangalore|Bellandur") or next((v for k,v in D.items()),None)
print(f"data_booking_source.json · {len(D)} clinics")
if b:
    chans=sorted(b.items(),key=lambda kv:-kv[1]['total'][0])
    print("  sample clinic wk0 by channel:", {k:v['total'][0] for k,v in chans if v['total'][0]>0})
