#!/usr/bin/env python3
"""Patch data_weekly_diag.json with purchased / revenue / doctors — sourced from the master demand
sheet (data_source_recon.json), so no Redshift pull is needed and the numbers match master exactly.

For each weekly-diag clinic (same slug key) it copies, remapped to the diagnostic's 26 ascending weeks:
  purchased.total[26] + purchased.by_cat[SH/STI/MH/Other]   (bottom.purchased / bottom.by_cat[c].purchased)
  revenue.rev[26]     + revenue.by_cat[...]                 (bottom.rev / bottom.by_cat[c].rev, ₹)
  doctors.count[26]                                          (# by_doctor providers with a booked SC that week)
  by_doctor = {doctor: {booked, done, purchased, rev}}       (remapped to 26 weeks, active doctors only)
Run: python3 scripts/patch_weekly_diag_extra.py     (no AWS needed)
"""
import os, json
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR=json.load(open(os.path.join(ROOT,'data_source_recon.json')))
DP=os.path.join(ROOT,'data_weekly_diag.json'); D=json.load(open(DP))
WDW=D['weeks']; N=len(WDW)
SRW=SR['_meta']['weeks']; srmap={w:i for i,w in enumerate(SRW)}   # sr weeks are newest-first
missing=[w for w in WDW if w not in srmap]
if missing: print('WARN: weeks not in source_recon → patched as 0 (source_recon lags a week):',missing[:3])   # QD overlay carries the real economics for the Quick Diagnostic; these D fields feed other views only
SIDX=[srmap.get(w,-1) for w in WDW]    # for each diagnostic week (ascending) -> index into sr arrays (-1 = week not yet in source_recon)
CATS=['SH','STI','MH','Other']
def remap(arr): return [ (arr[s] if 0<=s<len(arr) else 0) or 0 for s in SIDX ]

matched=0; tot_pur=0; tot_rev=0
for slug,c in D['clinics'].items():
    sc=SR['clinics'].get(slug)
    if not sc: continue
    b=sc.get('bottom',{}); bc=b.get('by_cat',{}) if isinstance(b.get('by_cat'),dict) else {}
    pur=remap(b.get('purchased',[])); rev=remap(b.get('rev',[]))
    c['purchased']={'total':pur, 'by_cat':{k:remap(bc.get(k,{}).get('purchased',[])) for k in CATS if isinstance(bc.get(k),dict)}}
    c['revenue']={'rev':rev, 'by_cat':{k:remap(bc.get(k,{}).get('rev',[])) for k in CATS if isinstance(bc.get(k),dict)}}
    bd=sc.get('by_doctor',{}) if isinstance(sc.get('by_doctor'),dict) else {}
    out_bd={}; docn=[0]*N
    for dr,f in bd.items():
        row={k:remap(f.get(k,[])) for k in ('booked','done','purchased','rev')}
        if not any(any(row[k]) for k in row): continue
        out_bd[dr]={k:row[k] for k in row if any(row[k])}
        for i in range(N):
            if row['booked'][i]>0: docn[i]+=1
    c['doctors']={'count':docn}
    if out_bd: c['by_doctor']=out_bd
    matched+=1; tot_pur+=sum(pur); tot_rev+=sum(rev)

if tot_pur==0: print('ABORT: 0 purchased across all clinics — not writing.'); raise SystemExit(1)

# ---- Online (national telehealth) — for the Offline/Online/All toggle ----
# Online has no clinics/availability/leads; it's national, with a per-city split. We expose booked/done/
# purchased/rev (+ by_cat) remapped to the 26 diagnostic weeks, national and by city.
def cube(src):   # src = {'total':{booked,done,purchased,rev}, 'by_cat':{cat:{...}}}
    if not isinstance(src,dict): return None
    tot=src.get('total',{}) if isinstance(src.get('total'),dict) else {}
    o={'booked':remap(tot.get('booked',[])),'done':remap(tot.get('done',[])),
       'purchased':remap(tot.get('purchased',[])),'rev':remap(tot.get('rev',[]))}
    bc=src.get('by_cat',{}) if isinstance(src.get('by_cat'),dict) else {}
    o['by_cat']={k:{'booked':remap(bc.get(k,{}).get('booked',[])),'done':remap(bc.get(k,{}).get('done',[])),
                    'purchased':remap(bc.get(k,{}).get('purchased',[])),'rev':remap(bc.get(k,{}).get('rev',[]))}
                 for k in CATS if isinstance(bc.get(k),dict)}
    return o
onb=SR['_meta'].get('online_bottom'); onbc=SR['_meta'].get('online_bottom_city',{})
D['online']={'national':cube(onb) if onb else None,
             'by_city':{ct:cube(v) for ct,v in onbc.items() if isinstance(v,dict)} if isinstance(onbc,dict) else {}}
on_tot=sum(D['online']['national']['booked']) if D['online']['national'] else 0

json.dump(D,open(DP,'w'),separators=(',',':'))
print('patched %d clinics · total purchased %d · total revenue %d · online booked(26wk) %d across %d cities'
      % (matched, tot_pur, tot_rev, on_tot, len(D['online']['by_city'])))
