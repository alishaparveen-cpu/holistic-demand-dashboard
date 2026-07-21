#!/usr/bin/env python3
"""One-off patch: 'Practo Online' (Practo code=PRACTO) is a virtual-consult pseudo-location — its
DB row has city='Practo Online' AND locality='Practo Online', so Practo telehealth leads were rendering
as a fake CITY and a fake CLINIC-in-city. Mirrors the permanent build_leads_city.py fix (drops code=PRACTO)
onto the already-built cubes so we don't need a full Redshift re-pull / risk snapshot drift.

  data_leads_city.json  : real-city cells with loc='Practo Online' → loc='' (not-attributed-to-a-clinic);
                          the whole 'Practo Online' CITY bucket → merged into '— no city · online / untracked'.
  data_clinic_funnel.json: drop the 'Practo Online' city + 'Practo Online|Practo Online' clinic entries.
"""
import json, os
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOCITY='— no city · online / untracked'

# ---- data_leads_city.json ----
p=os.path.join(ROOT,'data_leads_city.json'); d=json.load(open(p))
moved=cleared=0
# 1) clear the fake clinic-locality inside every real city
for city,node in d.items():
    if city in ('_meta','Practo Online'): continue
    for cel in node.get('cells',[]):
        if (cel.get('loc') or '')=='Practo Online':
            cel['loc']=''; cleared+=1
# 2) merge the fake 'Practo Online' CITY into the online/untracked bucket
if 'Practo Online' in d:
    cells=d['Practo Online'].get('cells',[])
    for cel in cells:
        if (cel.get('loc') or '')=='Practo Online': cel['loc']=''
    d.setdefault(NOCITY, {'cells':[]})
    d[NOCITY].setdefault('cells',[]).extend(cells); moved=len(cells)
    del d['Practo Online']
json.dump(d, open(p,'w'), separators=(',',':'))
print(f"data_leads_city.json: cleared {cleared} fake-clinic cells; moved {moved} 'Practo Online' city cells → '{NOCITY}'")

# ---- data_clinic_funnel.json ----
p2=os.path.join(ROOT,'data_clinic_funnel.json')
if os.path.exists(p2):
    cf=json.load(open(p2)); removed=[]
    for grp in ('cities','clinics'):
        if isinstance(cf.get(grp),dict):
            for k in list(cf[grp]):
                if 'Practo Online' in str(k): del cf[grp][k]; removed.append(f"{grp}/{k}")
    json.dump(cf, open(p2,'w'), separators=(',',':'))
    print(f"data_clinic_funnel.json: removed {removed}")
