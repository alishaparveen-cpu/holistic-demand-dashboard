#!/usr/bin/env python3
"""Build data_booking_episodes.json — the CLEAN, de-duplicated booking funnel where each patient's
reschedule/re-book chain is collapsed into ONE episode (see fetch_booking_episodes.sql).

One patient-intent = one booking, attributed to its first SC's week/channel/lead-age, with the
chain's FINAL outcome (done if ever completed; else missed/cancelled/pending). Reschedules become
a separate 'resched' rework count, not extra demand. 12 Monday-weeks, newest-first.

Per clinic:
  channel : episodes by channel, outcome split
  age     : episodes by 3-bucket lead age (tw/lw/old → labels)
  cube    : ch -> ageGroup -> seg(new/return) -> outcome -> [12]
  episodes/resched/gross : [12] totals for the clean vs gross reconciliation
"""
import json, os, subprocess, sys
from collections import defaultdict
HERE=os.path.dirname(__file__); RUN=os.path.join(HERE,'redshift_query.py'); ROOT=os.path.join(HERE,'..')
WEEKS=["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]
WI={w:i for i,w in enumerate(WEEKS)}
SUB=["total","done","missed","cancelled","resched","open"]
AGEMAP={'tw':'1 · Same week','lw':'2 · Last week','old':'3 · Older'}
def num(x):
    try: return int(x)
    except: return 0
sql=open(os.path.join(HERE,'fetch_booking_episodes.sql')).read()
p=subprocess.run([sys.executable,RUN],input=sql,capture_output=True,text=True)
if p.returncode!=0: raise RuntimeError(p.stderr[-400:])
rows=[l.split('\t') for l in p.stdout.splitlines() if l.strip()]
cube=defaultdict(lambda:defaultdict(lambda:defaultdict(lambda:defaultdict(lambda:defaultdict(lambda:[0]*12)))))
chan=defaultdict(lambda:defaultdict(lambda:{f:[0]*12 for f in SUB}))
age =defaultdict(lambda:defaultdict(lambda:{f:[0]*12 for f in SUB}))
resched=defaultdict(lambda:[0]*12); episodes=defaultdict(lambda:[0]*12)
for c in rows:
    if len(c)<9: continue
    city,clinic,wk,ch,ag,seg,out,e,rs=c[0],c[1],c[2],c[3],c[4],c[5],c[6],num(c[7]),num(c[8])
    if wk not in WI: continue
    i=WI[wk]; key=f"{city}|{clinic}"
    out=out if out in SUB else 'open'
    cube[key][ch][ag][seg][out][i]+=e
    chan[key][ch]['total'][i]+=e; chan[key][ch][out][i]+=e
    al=AGEMAP.get(ag,ag)
    age[key][al]['total'][i]+=e; age[key][al][out][i]+=e
    resched[key][i]+=rs; episodes[key][i]+=e
clinics=set(cube)|set(chan)|set(age)
def undefault(x):
    if isinstance(x,defaultdict): return {k:undefault(v) for k,v in x.items()}
    return x
OUT={"_meta":{"weeks":WEEKS,
    "source":"appointments collapsed to patient reschedule-chains (episodes) -> lead, offline clinics",
    "note":"CLEAN funnel: 1 patient-intent = 1 booking (reschedule chains within 14d collapsed). seg=new(first-ever)|return(14d+ later). outcome=done if ever completed, else final state. resched=rework events (chain rows - 1), NOT demand. episodes=unique bookings/wk.",
    "segments":["new","return"],
    "outcomes":SUB,
    "ages":["1 · Same week","2 · Last week","3 · Older"],
    "agegroups":{"tw":"This week","lw":"Last week","old":"Older"}}}
for k in clinics:
    OUT[k]={"channel":{ch:dict(f) for ch,f in chan[k].items()},
            "age":{a:dict(f) for a,f in age[k].items()},
            "cube":undefault(cube[k]),
            "episodes":episodes[k], "resched":resched[k],
            "gross":[episodes[k][i]+resched[k][i] for i in range(12)]}
json.dump(OUT,open(os.path.join(ROOT,"data_booking_episodes.json"),"w"),separators=(",",":"))
print(f"data_booking_episodes.json · {len(clinics)} clinics")
b=OUT.get("Bangalore|Bellandur")
if b: print(f"  Bellandur wk0: episodes {b['episodes'][0]} · reschedules {b['resched'][0]} · gross rows {b['gross'][0]}")
