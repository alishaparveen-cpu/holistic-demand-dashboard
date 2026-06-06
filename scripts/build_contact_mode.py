#!/usr/bin/env python3
"""Build data_contact_mode.json — clinic × week × original contact mode of booked patients."""
import json, os, subprocess, sys
from collections import defaultdict
HERE=os.path.dirname(__file__)
sql=open(os.path.join(HERE,'fetch_contact_mode.sql')).read()
p=subprocess.run([sys.executable,os.path.join(HERE,'redshift_query.py')],input=sql,capture_output=True,text=True)
if p.returncode!=0: raise RuntimeError(p.stderr[-300:])
d=defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
for line in p.stdout.splitlines():
    c=line.split('\t')
    if len(c)<4: continue
    d[c[0]][c[1]][c[2]]=int(c[3])
out={'_meta':{'source':'appointments(clinic,week)->patient->lead.origin','note':'Per clinic × booking week (Mon): original contact mode of patients who booked. Mode = lead.origin at creation. Walk-in/Ops = retool/staff.'},
     'by_clinic':{k:{wk:dict(m) for wk,m in wks.items()} for k,wks in d.items()}}
json.dump(out,open(os.path.join(HERE,'..','data_contact_mode.json'),'w'),separators=(',',':'))
print(f"data_contact_mode.json · {len(d)} clinics · weekly")
