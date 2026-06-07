#!/usr/bin/env python3
"""Build data_booking_source.json from the combined channel x age x outcome pull.
Per clinic/week we emit:
  channel : bookings by acquisition channel (full outcome split)   [single-dim view]
  age     : bookings by lead-age bucket      (full outcome split)   [single-dim view]
  joint   : channel -> age total counts                            [combined flow chart]
12 Monday-weeks, newest-first."""
import json, os, subprocess, sys
from collections import defaultdict
HERE=os.path.dirname(__file__); RUN=os.path.join(HERE,'redshift_query.py'); ROOT=os.path.join(HERE,'..')
WEEKS=["2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20",
       "2026-04-13","2026-04-06","2026-03-30","2026-03-23","2026-03-16","2026-03-09"]
WI={w:i for i,w in enumerate(WEEKS)}
SUB=["total","done","missed","resched_patient","resched_clinic","resched_noshow","cancelled","scheduled"]
def num(x):
    try: return int(x)
    except: return 0
sql=open(os.path.join(HERE,'fetch_booking_flow.sql')).read()
p=subprocess.run([sys.executable,RUN],input=sql,capture_output=True,text=True)
if p.returncode!=0: raise RuntimeError(p.stderr[-400:])
rows=[l.split('\t') for l in p.stdout.splitlines() if l.strip()]
# accumulate
chan=defaultdict(lambda:defaultdict(lambda:{f:[0]*12 for f in SUB}))   # clinic->ch->fields
age =defaultdict(lambda:defaultdict(lambda:{f:[0]*12 for f in SUB}))   # clinic->age->fields
joint=defaultdict(lambda:defaultdict(lambda:defaultdict(lambda:[0]*12)))  # clinic->ch->age->total
for c in rows:
    if len(c)<13: continue
    city,clinic,wk,ch,ag=c[0],c[1],c[2],c[3],c[4]
    if wk not in WI: continue
    i=WI[wk]; key=f"{city}|{clinic}"; vals=[num(x) for x in c[5:13]]
    for j,f in enumerate(SUB):
        chan[key][ch][f][i]+=vals[j]
        age[key][ag][f][i]+=vals[j]
    joint[key][ch][ag][i]+=vals[0]   # total only
clinics=set(chan)|set(age)|set(joint)
OUT={"_meta":{"weeks":WEEKS,
    "source":"appointments -> patient.lead_id -> lead (Screening Calls, offline clinics)",
    "note":"Per clinic/week, bookings traced to channel (utm_source/origin/gclid) and lead age (lead.created_at -> booked). 'joint' = channel->age total counts for the combined flow. 99.95% of booked patients link to a lead. Source of BOOKINGS, not all leads.",
    "channels":["Google Ads","Meta","Practo","Google Maps (GMB)","Organic","WhatsApp","Google organic","Other","Unknown","No lead record"],
    "ages":["1 · Same week","2 · Last week","3 · 2-4 weeks","4 · 1-3 months","5 · 3+ months","Unknown"]}}
for k in clinics:
    OUT[k]={
        "channel":{ch:dict(f) for ch,f in chan[k].items()},
        "age":{ag:dict(f) for ag,f in age[k].items()},
        "joint":{ch:{ag:list(t) for ag,t in ags.items()} for ch,ags in joint[k].items()},
    }
json.dump(OUT,open(os.path.join(ROOT,"data_booking_source.json"),"w"),separators=(",",":"))
print(f"data_booking_source.json · {len(clinics)} clinics")
b=OUT.get("Bangalore|Bellandur")
if b:
    print("  wk0 channel:", {k:v['total'][0] for k,v in sorted(b['channel'].items(),key=lambda kv:-kv[1]['total'][0]) if v['total'][0]>0})
    print("  wk0 age    :", {k:v['total'][0] for k,v in sorted(b['age'].items()) if v['total'][0]>0})
    print("  wk0 joint  :", {ch:{ag:t[0] for ag,t in ags.items() if t[0]>0} for ch,ags in b['joint'].items() if any(t[0]>0 for t in ags.values())})
