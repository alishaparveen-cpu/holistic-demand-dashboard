#!/usr/bin/env python3
"""Build data_booking_hod.json — per-clinic bookings by day-of-week × hour (IST, last 8 weeks)."""
import json, os, subprocess, sys
from collections import defaultdict
HERE=os.path.dirname(__file__)
sql=open(os.path.join(HERE,'fetch_booking_hod.sql')).read()
p=subprocess.run([sys.executable,os.path.join(HERE,'redshift_query.py')],input=sql,capture_output=True,text=True)
if p.returncode!=0: raise RuntimeError(p.stderr[-300:])
# fetch_booking_hod.sql now returns: k, wk, dow, hr, booked, done — aggregate over weeks (scorecard heatmap is a recent-weeks total)
d=defaultdict(lambda: defaultdict(lambda: defaultdict(lambda:[0,0])))
for line in p.stdout.splitlines():
    c=line.split('\t')
    if len(c)<6: continue
    cell=d[c[0]][str(int(c[2]))][str(int(c[3]))]
    cell[0]+=int(c[4]); cell[1]+=int(c[5])
d={k:{dw:{h:list(v) for h,v in hrs.items()} for dw,hrs in dows.items()} for k,dows in d.items()}
out={'_meta':{'source':'appointments start_time (IST), SC offline, recent weeks','note':'Per clinic: bookings by dow(0=Sun..6=Sat) × hour, summed over recent weeks. Roster planning.','window':'recent'},'by_clinic':d}
json.dump(out,open(os.path.join(HERE,'..','data_booking_hod.json'),'w'),separators=(',',':'))
print(f"data_booking_hod.json · {len(d)} clinics")
