#!/usr/bin/env python3
"""Build data_rebook_gap.json — reschedule events split by booking SEGMENT (new/return) AND by
gap-since-prior-SC, per clinic/week. Answers 'are reschedules on first-timers or genuine returns,
and how soon?'. 12 Monday-weeks, newest-first.
Output: { "City|Clinic": { "new": {"d0":[12],"d1_6":[12],"d7_13":[12]}, "return": {...} } } + _meta."""
import json, os, subprocess, sys
from collections import defaultdict
HERE=os.path.dirname(__file__); RUN=os.path.join(HERE,'redshift_query.py'); ROOT=os.path.join(HERE,'..')
WEEKS=["2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]
WI={w:i for i,w in enumerate(WEEKS)}
BUCKETS=["d0","d1_6","d7_13"]; SEGS=["new","return"]
def num(x):
    try: return int(x)
    except: return 0
sql=open(os.path.join(HERE,'fetch_rebook_gap.sql')).read()
p=subprocess.run([sys.executable,RUN],input=sql,capture_output=True,text=True)
if p.returncode!=0: raise RuntimeError(p.stderr[-400:])
rows=[l.split('\t') for l in p.stdout.splitlines() if l.strip()]
G=defaultdict(lambda:{s:{b:[0]*12 for b in BUCKETS} for s in SEGS})
for c in rows:
    if len(c)<6: continue
    city,clinic,wk,seg,gap=c[0],c[1],c[2],c[3],c[4]
    if wk not in WI or gap not in BUCKETS or seg not in SEGS: continue
    G[f"{city}|{clinic}"][seg][gap][WI[wk]]+=num(c[5])
OUT={"_meta":{"weeks":WEEKS,
    "segments":{"new":"New · first-time","return":"Genuine return"},
    "buckets":{"d0":"Same day","d1_6":"1–6 days later","d7_13":"7–13 days later"},
    "note":"Reschedule events (non-first SC within a <14d episode) by booking segment (new/return) × gap since prior SC, per clinic/week. Attributed to the episode's first-SC week."}}
for k,v in G.items(): OUT[k]=v
json.dump(OUT,open(os.path.join(ROOT,"data_rebook_gap.json"),"w"),separators=(",",":"))
print(f"data_rebook_gap.json · {len(G)} clinics")
b=G.get("Bangalore|Bellandur")
if b: print("  Bellandur wk0 new:", {bk:b['new'][bk][0] for bk in BUCKETS}, "return:", {bk:b['return'][bk][0] for bk in BUCKETS})
