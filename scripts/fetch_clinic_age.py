#!/usr/bin/env python3
# Per-clinic "age" = first completed/scheduled Screening Call date (open proxy), by locality.
# Stored as a date so the dashboard computes months-since live (stays fresh without rebuild).
import subprocess, json, os
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL="""SELECT loc.locality, MIN(a.created_at)::date first_sc
FROM allo_consultations.appointments a
JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.deleted_at IS NULL
WHERE a.deleted_at IS NULL AND loc.locality IS NOT NULL AND loc.locality<>''
GROUP BY 1"""
out=subprocess.run(['python3',os.path.join(ROOT,'scripts','redshift_query.py')],
                   input=SQL,capture_output=True,text=True).stdout
age={}
for line in out.splitlines():
    p=line.split('\t')
    if len(p)>=2 and len(p[1].strip())==10 and p[1].strip()[4]=='-':
        age[p[0].strip()]=p[1].strip()
if not age:
    print('ABORT: no rows (SSO/cluster?) — not writing'); raise SystemExit(1)
meta={'note':'open = first Screening Call date per clinic (locality), Redshift. months computed live in UI.'}
json.dump({'_meta':meta,'open':age},open(os.path.join(ROOT,'data_clinic_age.json'),'w'),separators=(',',':'))
print('wrote',len(age),'clinics')
