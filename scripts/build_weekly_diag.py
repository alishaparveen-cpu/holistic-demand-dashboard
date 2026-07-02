#!/usr/bin/env python3
"""Weekly Diagnostic — INPUTS (Availability → Demand → Conversion) → OUTPUT (bookings, done by category,
weekday/weekend-weighted bookings-per-active-day). All offline clinics.
Demand/Conversion/done-by-cat from data_l0_funnel.json; Availability (active weekday/weekend days + hours)
from roster_slots; bookings weekday/weekend split from bookings_data_raw (same phone_rank=1 offline basis as L0).
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
SC_ROSTER='cd02525c-1528-4047-a12c-1ad526c28c9a'
def tail(a): return (a or [0]*len(ALLW))[-N:]
def K(city,loc): return ((loc or '').strip().lower()+'|'+(city or '').strip().lower())

# ---- Availability: active weekday-days / weekend-days / hours per locality×week ----
avail={}
for r in q(f"""SELECT lc, city, wk,
    COUNT(DISTINCT CASE WHEN dow NOT IN (0,6) THEN dt END) wday_d,
    COUNT(DISTINCT CASE WHEN dow IN (0,6) THEN dt END) wend_d,
    ROUND(SUM(mins)/60.0,1) hrs
  FROM (SELECT loc.locality lc, loc.city city, DATE(rs.start_time+INTERVAL '5.5 hours') dt,
      EXTRACT(dow FROM (rs.start_time+INTERVAL '5.5 hours')) dow,
      TO_CHAR(DATE_TRUNC('week', rs.start_time+INTERVAL '5.5 hours'),'YYYY-MM-DD') wk,
      DATEDIFF(minute, rs.start_time, rs.end_time) mins
    FROM allo_consultations.roster_slots rs
    JOIN allo_health.locations loc ON loc.id=rs.location_id AND loc.deleted_at IS NULL AND LOWER(COALESCE(loc.locality,''))<>'' AND LOWER(COALESCE(loc.locality,''))<>'online'
    WHERE rs.type_id='{SC_ROSTER}' AND rs.start_time>='{LO}' AND rs.start_time<'{HI}') z
  GROUP BY 1,2,3"""):
    if len(r)>=6 and r[2] in idx:
        e=avail.setdefault(K(r[1],r[0]),{'wd':[0]*N,'we':[0]*N,'hr':[0.0]*N}); i=idx[r[2]]
        e['wd'][i]=int(r[3]); e['we'][i]=int(r[4]); e['hr'][i]=float(r[5])

# ---- Bookings weekday/weekend split (same basis as L0 booked) ----
bdow={}
for r in q(f"""SELECT locality, city, TO_CHAR(DATE_TRUNC('week', apt_create_dt::date),'YYYY-MM-DD') wk,
    SUM(CASE WHEN EXTRACT(dow FROM apt_create_dt::date) NOT IN (0,6) THEN 1 ELSE 0 END) wday,
    SUM(CASE WHEN EXTRACT(dow FROM apt_create_dt::date) IN (0,6) THEN 1 ELSE 0 END) wend
  FROM production.public.bookings_data_raw
  WHERE offline_location_flag=1 AND phone_rank=1 AND date(apt_create_dt)>='{LO}' AND date(apt_create_dt)<'{HI}'
  GROUP BY 1,2,3"""):
    if len(r)>=5 and r[2] in idx:
        e=bdow.setdefault(K(r[1],r[0]),{'wday':[0]*N,'wend':[0]*N}); i=idx[r[2]]
        e['wday'][i]=int(r[3]); e['wend'][i]=int(r[4])

# ---- Demand: offline leads per clinic × week (+ by source) from main_source_wise_leads ----
leadmap={}
for r in q(f"""SELECT call_location loc, TO_CHAR(DATE_TRUNC('week', created_on_date::date),'YYYY-MM-DD') wk,
    COALESCE(NULLIF(source,''),'Other') src, COUNT(*) n
  FROM production.public.main_source_wise_leads
  WHERE on_off_flag='Offline' AND created_on_date>='{LO}' AND created_on_date<'{HI}'
  GROUP BY 1,2,3"""):
    if len(r)>=4 and r[1] in idx and r[0] and r[0] not in ('True','Online',''):
        e=leadmap.setdefault(r[0].strip().lower(),{'tot':[0]*N,'src':{}}); i=idx[r[1]]; n=int(r[3])
        e['tot'][i]+=n; e['src'].setdefault(r[2],[0]*N)[i]+=n

def done_by_cat(c):
    cats={ct:[0]*N for ct in ['SH','STI','MH','Other']}
    for ch,cd in c.get('chan_cat',{}).items():
        for ct,md in cd.items():
            arr=tail(md.get('done_ever',[])); tgt=ct if ct in cats else 'Other'
            for i in range(N): cats[tgt][i]+=arr[i]
    return cats
def rate(num,den): return [round(num[i]/den[i],1) if den[i] else None for i in range(N)]

out={'weeks':WEEKS,'week_labels':WK_LABELS,'clinics':{}}
for slug,c in L0['clinics'].items():
    loc=c['disp'].split(' · ')[0]; k=K(c['city'],loc)
    booked=tail(c['tot']['booked']); done=tail(c['tot']['done_ever'])
    av=avail.get(k,{'wd':[0]*N,'we':[0]*N,'hr':[0.0]*N}); bd=bdow.get(k,{'wday':[0]*N,'wend':[0]*N})
    adays=[av['wd'][i]+av['we'][i] for i in range(N)]
    lm=leadmap.get(loc.strip().lower(),{'tot':[0]*N,'src':{}}); leads=lm['tot']
    leadsrc={s:lm['src'][s] for s in lm['src'] if sum(lm['src'][s])>0}
    out['clinics'][slug]={
        'disp':c['disp'],'city':c['city'],'loc':loc,
        'availability':{'active_days':adays,'wday_days':av['wd'],'wend_days':av['we'],'hours':av['hr']},
        'demand':{'leads':leads,'by_channel':leadsrc,'has_leads':sum(leads)>0},
        'conversion':{'leads':leads,'booked':booked,'done':done,
            'lead_book_pct':[round(100*booked[i]/leads[i]) if leads[i] else None for i in range(N)],
            'book_done_pct':[round(100*done[i]/booked[i]) if booked[i] else None for i in range(N)]},
        'output':{'bookings':booked,'done':done,'done_by_cat':done_by_cat(c),
            'per_weekday':rate(bd['wday'],av['wd']),'per_weekend':rate(bd['wend'],av['we']),
            'per_active_day':rate(booked,adays),'bk_wday':bd['wday'],'bk_wend':bd['wend']},
    }
json.dump(out,open(os.path.join(ROOT,'data_weekly_diag.json'),'w'),separators=(',',':'))
have=sum(1 for c in out['clinics'].values() if sum(c['availability']['active_days']))
print('wrote data_weekly_diag.json ·',len(out['clinics']),'clinics ·',have,'w/ roster ·',N,'wk')
