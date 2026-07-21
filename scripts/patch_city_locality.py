#!/usr/bin/env python3
"""Apply the build_leads_city.py city/locality-attribution fix onto the already-built cube
(no Redshift re-pull / no snapshot drift):
  1. CITY_ALIAS: merge locality-name 'cities' into their real city  ('Thane West' → 'Thane').
  2. Null any clinic-locality that belongs to a DIFFERENT known city (wrong-city clinic) —
     only the clinic grain changes; city / channel / booked / done totals are untouched.
Then rebuild data_campaign_compose.json so the Google-Ads Compose page reflects it.
"""
import json, os, subprocess
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GMAP=json.load(open(os.path.join(ROOT,'data_gmb_number_clinic.json')))
LOC2CITY={}
for v in set(GMAP.values()):
    if '|' in v: c,l=v.split('|',1); LOC2CITY[l]=c
CITY_ALIAS={'Thane West':'Thane'}

p=os.path.join(ROOT,'data_leads_city.json'); d=json.load(open(p))
# 1) merge alias cities
for old,new in CITY_ALIAS.items():
    if old in d:
        d.setdefault(new,{'cells':[]}); d[new].setdefault('cells',[]).extend(d[old].get('cells',[])); del d[old]
        print(f"merged city '{old}' → '{new}'")
# 2) null cross-city localities
nulled=0
for city,node in d.items():
    if city=='_meta': continue
    for cel in node.get('cells',[]):
        loc=cel.get('loc') or ''
        if loc and loc!=city:
            home=LOC2CITY.get(loc)
            if home and home!=city: cel['loc']=''; nulled+=1
json.dump(d, open(p,'w'), separators=(',',':'))
print(f"nulled {nulled} wrong-city clinic-locality cells across {len([c for c in d if c!='_meta'])} cities")

# rebuild the compose cube from the corrected leads cube
r=subprocess.run(['python3', os.path.join(ROOT,'scripts','build_campaign_compose.py')], capture_output=True, text=True)
print(r.stdout.strip() or r.stderr.strip())
