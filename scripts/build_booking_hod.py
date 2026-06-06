#!/usr/bin/env python3
"""Build data_booking_hod.json — per-clinic bookings by day-of-week × hour (IST, last 8 weeks)."""
import json, os, subprocess, sys
from collections import defaultdict
HERE=os.path.dirname(__file__)
sql=open(os.path.join(HERE,'fetch_booking_hod.sql')).read()
p=subprocess.run([sys.executable,os.path.join(HERE,'redshift_query.py')],input=sql,capture_output=True,text=True)
if p.returncode!=0: raise RuntimeError(p.stderr[-300:])
d=defaultdict(lambda: defaultdict(dict))
for line in p.stdout.splitlines():
    c=line.split('\t')
    if len(c)<5: continue
    d[c[0]][str(int(c[1]))][str(int(c[2]))]=[int(c[3]),int(c[4])]
out={'_meta':{'source':'appointments start_time (IST), SC offline, last 8 weeks','note':'Per clinic: bookings by dow(0=Sun..6=Sat) × hour. Roster planning.','window':'8wk'},'by_clinic':{k:dict(v) for k,v in d.items()}}
json.dump(out,open(os.path.join(HERE,'..','data_booking_hod.json'),'w'),separators=(',',':'))
print(f"data_booking_hod.json · {len(d)} clinics")
