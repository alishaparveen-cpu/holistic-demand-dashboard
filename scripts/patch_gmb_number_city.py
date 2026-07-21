#!/usr/bin/env python3
"""Mirror the build_leads_city.py city-priority fix onto the already-built cube (no re-pull):
an inbound CALL lead's dialed number IS a specific clinic's GMB exophone → that number's city+locality
(data_gmb_number_clinic.json) is the most authoritative signal and must outrank the territory registry
(which mis-groups e.g. Gandhinagar exophones under Ahmedabad, and dumped many GMB calls into a phantom
'Delhi' bucket). Move each such lead to its dialed clinic's city and restore its clinic-locality.
Then rebuild data_campaign_compose.json.
"""
import json, os, subprocess
from collections import Counter
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GMAP=json.load(open(os.path.join(ROOT,'data_gmb_number_clinic.json')))
NUM_CITY={n:v.split('|')[0] for n,v in GMAP.items() if '|' in v and v.split('|')[0]!='Practo Online'}
NUM_LOC ={n:v.split('|')[1] for n,v in GMAP.items() if '|' in v and v.split('|')[0]!='Practo Online'}

p=os.path.join(ROOT,'data_leads_city.json'); d=json.load(open(p))
moved=0; net=Counter()
for city in [c for c in d if c!='_meta']:
    keep=[]
    for cel in d[city]['cells']:
        num=cel.get('num')
        if cel.get('md')=='call' and num in NUM_CITY and NUM_CITY[num]!=city:
            tc=NUM_CITY[num]
            cel['loc']=NUM_LOC[num]                    # restore the correct clinic locality
            d.setdefault(tc,{'cells':[]}); d[tc].setdefault('cells',[]).append(cel)
            s=sum(x for x in cel.get('w',[]) if isinstance(x,(int,float)))
            moved+=s; net[tc]+=s; net[city]-=s
        else:
            keep.append(cel)
    d[city]['cells']=keep
# drop any city bucket left with no leads at all (e.g. phantom 'Delhi')
for city in [c for c in d if c!='_meta']:
    if not any(sum(x for x in cel.get('w',[]) if isinstance(x,(int,float)))>0 for cel in d[city]['cells']):
        del d[city]; print(f"removed now-empty city bucket '{city}'")
json.dump(d, open(p,'w'), separators=(',',':'))
print(f"moved {moved} call-leads to their dialed-clinic city. net city change:")
for c,v in sorted(net.items(), key=lambda x:-x[1]):
    if abs(v)>=3: print(f"  {c}: {'+' if v>0 else ''}{v}")

r=subprocess.run(['python3', os.path.join(ROOT,'scripts','build_campaign_compose.py')], capture_output=True, text=True)
print(r.stdout.strip() or r.stderr.strip())
