#!/usr/bin/env python3
"""Build data_booking_source.json — per clinic/week, booked SC appts split two ways:
  channel: acquisition channel (via patient.lead_id -> lead.utm_source/origin/gclid)
  age:     how stale the lead was when it booked (lead.created_at -> appt.created_at)
each with the full outcome breakdown. 12 Monday-weeks, newest-first."""
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
def collect(sqlfile):
    D={}
    for c in q(sqlfile):
        if len(c)<12: continue
        city,clinic,wk,seg=c[0],c[1],c[2],c[3]
        if wk not in WI: continue
        o=D.setdefault(f"{city}|{clinic}",{})
        s=o.setdefault(seg,{f:[0]*12 for f in SUB})
        for j,f in enumerate(SUB): s[f][WI[wk]]=num(c[4+j])
    return D
chan=collect('fetch_booking_source.sql')
age=collect('fetch_booking_age.sql')
clinics=set(chan)|set(age)
OUT={"_meta":{"weeks":WEEKS,
    "source":"appointments -> patient.lead_id -> lead (Screening Calls, offline clinics)",
    "note":"Per clinic/week, bookings split two ways — channel (utm_source/origin/gclid) and age (lead.created_at -> booked). 99.95% of booked patients link to a lead; ~95% have a tagged source. Source of BOOKINGS, not all leads.",
    "channels":["Google Ads","Meta","Practo","Google Maps (GMB)","Organic","WhatsApp","Google organic","Other","Unknown","No lead record"],
    "ages":["1 · Same week","2 · Last week","3 · 2-4 weeks","4 · 1-3 months","5 · 3+ months","Unknown"]}}
for k in clinics:
    OUT[k]={"channel":chan.get(k,{}),"age":age.get(k,{})}
json.dump(OUT,open(os.path.join(ROOT,"data_booking_source.json"),"w"),separators=(",",":"))
print(f"data_booking_source.json · {len(clinics)} clinics")
b=OUT.get("Bangalore|Bellandur")
if b:
    print("  wk0 channel:", {k:v['total'][0] for k,v in sorted(b['channel'].items(),key=lambda kv:-kv[1]['total'][0]) if v['total'][0]>0})
    print("  wk0 age    :", {k:v['total'][0] for k,v in sorted(b['age'].items()) if v['total'][0]>0})
