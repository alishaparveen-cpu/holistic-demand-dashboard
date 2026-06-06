#!/usr/bin/env python3
"""Build data_avail_hod.json — per-clinic dow×hour weekly arrays (b/s/x/a) for windowable heatmaps."""
import json, os, subprocess, sys
from collections import defaultdict
HERE=os.path.dirname(__file__)
def run(f):
    sql=open(os.path.join(HERE,f)).read()
    p=subprocess.run([sys.executable,os.path.join(HERE,'redshift_query.py')],input=sql,capture_output=True,text=True)
    if p.returncode!=0: raise RuntimeError(p.stderr[-300:])
    return [l.split('\t') for l in p.stdout.splitlines() if l.strip()]
weeks=set(); book=defaultdict(lambda: defaultdict(lambda: defaultdict(dict))); slot=defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
for r in run('fetch_booking_hod.sql'):        # k,wk,dow,hr,booked,done
    if len(r)<6: continue
    weeks.add(r[1]); book[r[0]][str(int(r[2]))][str(int(r[3]))][r[1]]=int(r[4])
for r in run('fetch_slot_hod.sql'):           # k,wk,dow,hr,sched,shrunk,avail
    if len(r)<7: continue
    weeks.add(r[1]); slot[r[0]][str(int(r[2]))][str(int(r[3]))][r[1]]=[int(r[4]),int(r[5]),int(r[6])]
weeks=sorted(weeks); wi={w:i for i,w in enumerate(weeks)}; N=len(weeks)
out={}
for k in set(book)|set(slot):
    cells={}
    for dow in set(book[k])|set(slot[k]):
        hd={}
        for hr in set(book[k].get(dow,{}))|set(slot[k].get(dow,{})):
            b=[0]*N;s=[0]*N;x=[0]*N;a=[0]*N
            for wk,v in book[k].get(dow,{}).get(hr,{}).items(): b[wi[wk]]=v
            for wk,v in slot[k].get(dow,{}).get(hr,{}).items(): s[wi[wk]],x[wi[wk]],a[wi[wk]]=v
            hd[hr]={'b':b,'s':s,'x':x,'a':a}
        cells[dow]=hd
    out[k]=cells
res={'_meta':{'source':'appointments + roster_slots/appointment_blocks by week×dow×hour (IST)','note':'Per clinic dow×hour: b/s/x/a as weekly arrays (oldest→newest). UI sums last N weeks.','weeks':weeks},'weeks':weeks,'by_clinic':out}
json.dump(res,open(os.path.join(HERE,'..','data_avail_hod.json'),'w'),separators=(',',':'))
print(f"data_avail_hod.json · {len(out)} clinics · {N} weeks")
