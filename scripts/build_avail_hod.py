#!/usr/bin/env python3
"""Build data_avail_hod.json — per-clinic dow×hour bookings + slots/shrinkage (hour-granular availability)."""
import json, os, subprocess, sys
from collections import defaultdict
HERE=os.path.dirname(__file__)
def run(f):
    sql=open(os.path.join(HERE,f)).read()
    p=subprocess.run([sys.executable,os.path.join(HERE,'redshift_query.py')],input=sql,capture_output=True,text=True)
    if p.returncode!=0: raise RuntimeError(p.stderr[-300:])
    return [l.split('\t') for l in p.stdout.splitlines() if l.strip()]
cell=defaultdict(lambda: defaultdict(dict))
for r in run('fetch_booking_hod.sql'):           # k,dow,hr,booked,done
    if len(r)<5: continue
    cell[r[0]].setdefault(str(int(r[1])),{}).setdefault(str(int(r[2])),{})['b']=int(r[3])
for r in run('fetch_slot_hod.sql'):              # k,dow,hr,sched,shrunk,avail
    if len(r)<6: continue
    d=cell[r[0]].setdefault(str(int(r[1])),{}).setdefault(str(int(r[2])),{})
    d['s'],d['x'],d['a']=int(r[3]),int(r[4]),int(r[5])
out={'_meta':{'source':'appointments + roster_slots/appointment_blocks by dow×hour (IST,8wk)','note':'b=bookings,s=scheduled,x=shrunk(blocked),a=available per dow(0=Sun..6=Sat)×hour. Hour loss=sum (b/a)×x.'},
     'by_clinic':{k:{dw:dict(h) for dw,h in v.items()} for k,v in cell.items()}}
json.dump(out,open(os.path.join(HERE,'..','data_avail_hod.json'),'w'),separators=(',',':'))
print(f"data_avail_hod.json · {len(cell)} clinics")
