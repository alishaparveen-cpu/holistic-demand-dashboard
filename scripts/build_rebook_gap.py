#!/usr/bin/env python3
"""Build data_rebook_gap.json — re-booked SCs by gap-since-prior-SC bucket, per clinic/week.
Answers 'this week's re-books are re-books from which date?'. 12 Monday-weeks, newest-first.
Output: { "City|Clinic": { "d0":[12], "d1_6":[12], "d7_13":[12] } } + _meta."""
import json, os, subprocess, sys
from collections import defaultdict
HERE=os.path.dirname(__file__); RUN=os.path.join(HERE,'redshift_query.py'); ROOT=os.path.join(HERE,'..')
WEEKS=["2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20",
       "2026-04-13","2026-04-06","2026-03-30","2026-03-23","2026-03-16","2026-03-09"]
WI={w:i for i,w in enumerate(WEEKS)}
BUCKETS=["d0","d1_6","d7_13"]
def num(x):
    try: return int(x)
    except: return 0
sql=open(os.path.join(HERE,'fetch_rebook_gap.sql')).read()
p=subprocess.run([sys.executable,RUN],input=sql,capture_output=True,text=True)
if p.returncode!=0: raise RuntimeError(p.stderr[-400:])
rows=[l.split('\t') for l in p.stdout.splitlines() if l.strip()]
G=defaultdict(lambda:{b:[0]*12 for b in BUCKETS})
for c in rows:
    if len(c)<5: continue
    city,clinic,wk,gap=c[0],c[1],c[2],c[3]
    if wk not in WI or gap not in BUCKETS: continue
    G[f"{city}|{clinic}"][gap][WI[wk]]+=num(c[4])
OUT={"_meta":{"weeks":WEEKS,
    "buckets":{"d0":"Same day","d1_6":"1–6 days later","d7_13":"7–13 days later"},
    "note":"Re-booked Screening Calls (new SC within 14d of prior SC) by gap since the prior SC, per clinic/week."}}
for k,v in G.items(): OUT[k]=v
json.dump(OUT,open(os.path.join(ROOT,"data_rebook_gap.json"),"w"),separators=(",",":"))
print(f"data_rebook_gap.json · {len(G)} clinics")
b=G.get("Bangalore|Bellandur")
if b: print("  Bellandur wk0:", {bk:b[bk][0] for bk in BUCKETS})
