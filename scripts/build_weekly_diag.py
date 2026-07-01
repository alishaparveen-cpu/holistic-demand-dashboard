#!/usr/bin/env python3
"""Weekly Diagnostic — per-clinic top-down funnel (Availability → Demand → Conversion → Velocity)
for the 'earliest broken stage' RCA + founder portfolio scan.
ALL offline clinics: Demand/Conversion/Velocity from data_l0_funnel.json (booked/done by channel, weekly);
Availability (active days + roster hours) pulled from roster_slots. Last 26 weeks.
Run: AWS_PROFILE=redshift-data python3 scripts/build_weekly_diag.py"""
import os, json, subprocess
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def q(sql):
    out=subprocess.run(['python3',os.path.join(ROOT,'scripts','redshift_query.py')],input=sql,capture_output=True,text=True).stdout
    return [l.split('\t') for l in out.splitlines() if l.strip()]

L0=json.load(open(os.path.join(ROOT,'data_l0_funnel.json')))
ALLW=L0['_meta']['weeks']; ALLLAB=L0['_meta']['week_labels']
N=26; WEEKS=ALLW[-N:]; WK_LABELS=[ALLLAB[w] for w in WEEKS]; idx={w:i for i,w in enumerate(WEEKS)}
LO=WEEKS[0]; HI='2026-06-29'
SC_ROSTER_TYPE='cd02525c-1528-4047-a12c-1ad526c28c9a'
def tail(a): return (a or [0]*len(ALLW))[-N:]

# ---- availability per locality × week (one pull, all clinics) ----
locs=sorted({c['disp'].split(' · ')[0] for c in L0['clinics'].values()})
inloc="','".join(l.replace("'","''") for l in locs)
avail={}   # (locality) -> {'ad':[..],'hr':[..]}
for r in q(f"""SELECT loc.locality lc, TO_CHAR(DATE_TRUNC('week', rs.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') wk,
    COUNT(DISTINCT DATE(rs.start_time + INTERVAL '5.5 hours')) adays,
    ROUND(SUM(DATEDIFF(minute, rs.start_time, rs.end_time))/60.0,1) hrs
  FROM allo_consultations.roster_slots rs
  JOIN allo_health.locations loc ON loc.id=rs.location_id AND loc.locality IN ('{inloc}') AND loc.deleted_at IS NULL
  WHERE rs.type_id='{SC_ROSTER_TYPE}' AND rs.start_time>='{LO}' AND rs.start_time<'{HI}'
  GROUP BY 1,2"""):
    if len(r)>=4 and r[1] in idx:
        e=avail.setdefault(r[0],{'ad':[0]*N,'hr':[0.0]*N}); i=idx[r[1]]; e['ad'][i]=int(r[2]); e['hr'][i]=float(r[3])

out={'weeks':WEEKS,'week_labels':WK_LABELS,'clinics':{}}
for slug,c in L0['clinics'].items():
    loc=c['disp'].split(' · ')[0]
    booked=tail(c['tot']['booked']); done=tail(c['tot']['done_ever'])
    av=avail.get(loc,{'ad':[0]*N,'hr':[0.0]*N})
    # demand by booking channel (drop all-zero channels)
    bych={ch:tail(c['chan'][ch]['booked']) for ch in c.get('chan',{}) if sum(tail(c['chan'][ch]['booked']))>0}
    out['clinics'][slug]={
        'disp':c['disp'],'city':c['city'],'loc':loc,
        'availability':{'active_days':av['ad'],'hours':av['hr']},
        'demand':{'bookings':booked,'by_channel':bych},
        'conversion':{'booked':booked,'done':done,
            'book_done_pct':[round(100*done[i]/booked[i]) if booked[i] else None for i in range(N)]},
        'velocity':{'bookings':booked,
            'per_active_day':[round(booked[i]/av['ad'][i],1) if av['ad'][i] else None for i in range(N)]},
    }
json.dump(out,open(os.path.join(ROOT,'data_weekly_diag.json'),'w'),separators=(',',':'))
have_av=sum(1 for c in out['clinics'].values() if sum(c['availability']['active_days']))
print('wrote data_weekly_diag.json ·',len(out['clinics']),'clinics ·',have_av,'with roster availability ·',N,'weeks')
