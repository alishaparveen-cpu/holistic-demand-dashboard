#!/usr/bin/env python3
"""Build data_lead_conv.json — lead→booking conversion by contact mode (weekly) + source (4wk)."""
import json, os, subprocess, sys
from collections import defaultdict
HERE=os.path.dirname(__file__); RUN=os.path.join(HERE,'redshift_query.py')
def q(f):
    sql=open(os.path.join(HERE,f)).read()
    p=subprocess.run([sys.executable,RUN],input=sql,capture_output=True,text=True)
    if p.returncode!=0: raise RuntimeError(p.stderr[-300:])
    return [l.split('\t') for l in p.stdout.splitlines() if l.strip()]
modes=defaultdict(lambda: defaultdict(lambda:[0,0])); weeks=set()
for r in q('fetch_lead_conv.sql'):
    if len(r)<4: continue
    wk,mode=r[0],r[1][2:]; weeks.add(wk); modes[mode][wk]=[int(r[2]),int(r[3])]
weeks=sorted(weeks)
order=['Inbound call','Outbound call','WhatsApp','Website self-serve','Other']
by_mode={m:{'leads':[modes[m].get(w,[0,0])[0] for w in weeks],'booked':[modes[m].get(w,[0,0])[1] for w in weeks]} for m in order if m in modes}
by_source=[{'src':r[0],'leads':int(r[1]),'booked':int(r[2]),'done':int(r[3])} for r in q('fetch_lead_conv_src.sql') if len(r)>=4]
out={'_meta':{'source':'allo_persons.lead + exotel_calls + SC appts','note':'Lead→booking by contact mode (priority inbound>outbound>WhatsApp>website). booked within 14d. by_source=4wk. NETWORK-level.','window':(weeks[0]+'..'+weeks[-1]) if weeks else ''},'weeks':weeks,'by_mode':by_mode,'by_source':by_source}
json.dump(out,open(os.path.join(HERE,'..','data_lead_conv.json'),'w'),separators=(',',':'))
print(f"data_lead_conv.json · {len(weeks)} wks · {len(by_mode)} modes · {len(by_source)} sources")
