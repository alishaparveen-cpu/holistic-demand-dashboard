#!/usr/bin/env python3
"""Build data_contact_mode.json — clinic-level original contact mode of booked patients (4wk)."""
import json, os, subprocess, sys
from collections import defaultdict
HERE=os.path.dirname(__file__)
sql=open(os.path.join(HERE,'fetch_contact_mode.sql')).read()
p=subprocess.run([sys.executable,os.path.join(HERE,'redshift_query.py')],input=sql,capture_output=True,text=True)
if p.returncode!=0: raise RuntimeError(p.stderr[-300:])
d=defaultdict(lambda: defaultdict(int))
for line in p.stdout.splitlines():
    c=line.split('\t')
    if len(c)<3: continue
    d[c[0]][c[1]]=int(c[2])
out={'_meta':{'source':'appointments(clinic)->patient->lead.origin · last 4 weeks','note':'Of patients who booked an SC at this clinic, their ORIGINAL contact mode. Clinic-accurate.'},'by_clinic':{k:dict(v) for k,v in d.items()}}
json.dump(out,open(os.path.join(HERE,'..','data_contact_mode.json'),'w'),separators=(',',':'))
print(f"data_contact_mode.json · {len(d)} clinics")
