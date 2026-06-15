#!/usr/bin/env python3
"""Build data_booking_source.json from the full booking cube
(channel x lead-age-group x New/FU x outcome, per clinic/week).
Emits per clinic:
  channel : bookings by channel, full outcome split   [single-dim 'Where they came from' view]
  age     : bookings by 5-bucket lead age, outcomes    [single-dim 'Lead age' view]
  cube    : nested ch -> ageGroup(tw/lw/old) -> seg(new/fu) -> outcome -> [12]  [focusable Full flow]
12 Monday-weeks, newest-first."""
import json, os, subprocess, sys
from collections import defaultdict
HERE=os.path.dirname(__file__); RUN=os.path.join(HERE,'redshift_query.py'); ROOT=os.path.join(HERE,'..')
WEEKS=["2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23"]
WI={w:i for i,w in enumerate(WEEKS)}
SUB=["total","done","missed","resched_patient","resched_clinic","resched_noshow","cancelled","scheduled"]
AGEMAP={'tw':'1 · Same week','lw':'2 · Last week','old':'3 · Older'}   # 5-bucket age view collapses to 3 here (cube already grouped)
def num(x):
    try: return int(x)
    except: return 0
sql=open(os.path.join(HERE,'fetch_booking_cube.sql')).read()
p=subprocess.run([sys.executable,RUN],input=sql,capture_output=True,text=True)
if p.returncode!=0: raise RuntimeError(p.stderr[-400:])
rows=[l.split('\t') for l in p.stdout.splitlines() if l.strip()]
# cube[clinic][ch][agegrp][seg][out] = [12]
cube=defaultdict(lambda:defaultdict(lambda:defaultdict(lambda:defaultdict(lambda:defaultdict(lambda:[0]*12)))))
chan=defaultdict(lambda:defaultdict(lambda:{f:[0]*12 for f in SUB}))   # clinic->ch->fields
age =defaultdict(lambda:defaultdict(lambda:{f:[0]*12 for f in SUB}))   # clinic->ageLabel->fields
for c in rows:
    if len(c)<8: continue
    city,clinic,wk,ch,ag,seg,out=c[0],c[1],c[2],c[3],c[4],c[5],c[6]
    if wk not in WI: continue
    i=WI[wk]; key=f"{city}|{clinic}"; n=num(c[7])
    cube[key][ch][ag][seg][out][i]+=n
    # channel marginal (full outcomes)
    chan[key][ch]['total'][i]+=n
    if out in chan[key][ch]: chan[key][ch][out][i]+=n
    # age marginal (collapsed labels, full outcomes)
    al=AGEMAP.get(ag,ag)
    age[key][al]['total'][i]+=n
    if out in age[key][al]: age[key][al][out][i]+=n
clinics=set(cube)|set(chan)|set(age)
OUT={"_meta":{"weeks":WEEKS,
    "source":"appointments -> patient.lead_id -> lead (Screening Calls, offline clinics)",
    "note":"Full booking cube: channel x lead-age(tw/lw/old) x new/fu x outcome, per clinic/week. 99.95% of booked patients link to a lead. Source of BOOKINGS, not all leads.",
    "channels":["Google Ads","Google Maps (GMB)","Practo","Meta","JustDial","Organic","Walk-in","Other","No tag"],
    "ages":["1 · Same week","2 · Last week","3 · Older"],
    "agegroups":{"tw":"This week","lw":"Last week","old":"Older"}}}
def undefault(x):
    if isinstance(x,defaultdict): return {k:undefault(v) for k,v in x.items()}
    return x
for k in clinics:
    OUT[k]={"channel":{ch:dict(f) for ch,f in chan[k].items()},
            "age":{a:dict(f) for a,f in age[k].items()},
            "cube":undefault(cube[k])}
json.dump(OUT,open(os.path.join(ROOT,"data_booking_source.json"),"w"),separators=(",",":"))
print(f"data_booking_source.json · {len(clinics)} clinics")
b=OUT.get("Bangalore|Bellandur")
if b:
    print("  wk0 channel:", {k:v['total'][0] for k,v in sorted(b['channel'].items(),key=lambda kv:-kv[1]['total'][0]) if v['total'][0]>0})
    # cube sanity: New same-week outcomes
    cu=b['cube']; tot=0
    for ch,ags in cu.items():
        for ag,segs in ags.items():
            for seg,outs in segs.items():
                for o,arr in outs.items(): tot+=arr[0]
    print("  cube wk0 total bookings:", tot)
