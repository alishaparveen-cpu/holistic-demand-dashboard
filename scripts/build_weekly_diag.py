#!/usr/bin/env python3
"""Weekly Diagnostic — 5-stage clinic funnel, all offline clinics, last 26 weeks.
  1 Availability  (active weekday/weekend days + hours, roster_slots)
  2 Demand        (offline leads, main_source_wise_leads) + lead->book%
  3 Bookings      (ALL SC, bookings_data_raw) split new-this-week / older-lead / rebooked / relapse
  4 Done          book->done% + done by category (SH/STI/MH/Other, MH via ICD/kw override)
  5 Velocity      bookings/active-day = weekday-rate & weekend-rate combined
Run: AWS_PROFILE=redshift-data python3 scripts/build_weekly_diag.py"""
import os, json, subprocess
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def q(sql):
    out=subprocess.run(['python3',os.path.join(ROOT,'scripts','redshift_query.py')],input=sql,capture_output=True,text=True).stdout
    return [l.split('\t') for l in out.splitlines() if l.strip()]
L0=json.load(open(os.path.join(ROOT,'data_l0_funnel.json')))
ALLW=L0['_meta']['weeks']; ALLLAB=L0['_meta']['week_labels']
N=26; WEEKS=ALLW[-N:]; WK_LABELS=[ALLLAB[w] for w in WEEKS]; idx={w:i for i,w in enumerate(WEEKS)}
LO=WEEKS[0]; HI='2026-06-29'; SC_ROSTER='cd02525c-1528-4047-a12c-1ad526c28c9a'
def K(city,loc): return (loc or '').strip().lower()+'|'+(city or '').strip().lower()
def Z(): return [0]*N
def zput(d,k,i,v): d.setdefault(k,Z())[i]=d.get(k,Z())[i] if False else d.setdefault(k,Z())[i]

# ---- 1 Availability ---- (active days SC-based; hours split into all-roster vs screening-call only)
avail={}
for r in q(f"""SELECT lc, city, wk,
    COUNT(DISTINCT CASE WHEN is_sc AND dow NOT IN (0,6) THEN dt END) wd,
    COUNT(DISTINCT CASE WHEN is_sc AND dow IN (0,6) THEN dt END) we,
    ROUND(SUM(CASE WHEN is_sc THEN mins ELSE 0 END)/60.0,1) sc_hrs,
    ROUND(SUM(mins)/60.0,1) all_hrs
  FROM (SELECT loc.locality lc, loc.city city, DATE(rs.start_time+INTERVAL '5.5 hours') dt,
      EXTRACT(dow FROM (rs.start_time+INTERVAL '5.5 hours')) dow,
      TO_CHAR(DATE_TRUNC('week', rs.start_time+INTERVAL '5.5 hours'),'YYYY-MM-DD') wk,
      DATEDIFF(minute, rs.start_time, rs.end_time) mins,
      (rs.type_id='{SC_ROSTER}') is_sc
    FROM allo_consultations.roster_slots rs
    JOIN allo_health.locations loc ON loc.id=rs.location_id AND loc.deleted_at IS NULL AND LOWER(COALESCE(loc.locality,'')) NOT IN ('','online')
    WHERE rs.start_time>='{LO}' AND rs.start_time<'{HI}') z GROUP BY 1,2,3"""):
    if len(r)>=7 and r[2] in idx:
        e=avail.setdefault(K(r[1],r[0]),{'wd':Z(),'we':Z(),'hr':[0.0]*N,'ahr':[0.0]*N}); i=idx[r[2]]
        e['wd'][i]=int(r[3]); e['we'][i]=int(r[4]); e['hr'][i]=float(r[5]); e['ahr'][i]=float(r[6])

# ---- 2 Demand: leads ----
leadmap={}
for r in q(f"""SELECT call_location loc, TO_CHAR(DATE_TRUNC('week', created_on_date::date),'YYYY-MM-DD') wk,
    COALESCE(NULLIF(source,''),'Other') src, COUNT(*) n FROM production.public.main_source_wise_leads
  WHERE on_off_flag='Offline' AND created_on_date>='{LO}' AND created_on_date<'{HI}' GROUP BY 1,2,3"""):
    if len(r)>=4 and r[1] in idx and r[0] and r[0] not in ('True','Online',''):
        e=leadmap.setdefault(r[0].strip().lower(),{'tot':Z(),'src':{}}); i=idx[r[1]]; n=int(r[3])
        e['tot'][i]+=n; e['src'].setdefault(r[2],Z())[i]+=n

# ---- 3/4/5 Bookings (ALL SC) taxonomy + done-by-cat + weekday/weekend, from bookings_data_raw ----
bk={}
for r in q(f"""WITH b0 AS (
    SELECT phone_no, appointment_id, city, locality, apt_create_dt::date dt, apt_status_final st, phone_rank, diag_cat,
      SUM(CASE WHEN apt_status_final='COMPLETED' THEN 1 ELSE 0 END) OVER (PARTITION BY phone_no ORDER BY apt_create_dt ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) prior_done
    FROM production.public.bookings_data_raw
    WHERE offline_location_flag=1 AND date(apt_create_dt)>='2025-01-01' AND date(apt_create_dt)<'{HI}'),
  lw AS (SELECT phone_no1 ph, MIN(DATE_TRUNC('week',created_on_date::date)) lwk FROM production.public.main_source_wise_leads WHERE on_off_flag='Offline' GROUP BY 1),
  mh AS (SELECT DISTINCT e.appointment_id ap FROM allo_prod.allo_encounters.encounters e
    JOIN allo_prod.allo_observations.diagnoses d ON d.encounter_id=e.id AND d.deleted_at IS NULL
    WHERE e.deleted_at IS NULL AND e.appointment_id IS NOT NULL
      AND (d.description LIKE '%(6A%' OR d.description LIKE '%(6B%' OR d.description LIKE '%(6C%' OR d.description LIKE '%(6D%' OR d.description LIKE '%(6E%'
        OR d.description ILIKE '%depress%' OR d.description ILIKE '%bipolar%' OR d.description ILIKE '%psychosis%' OR d.description ILIKE '%adhd%' OR d.description ILIKE '%ocd%' OR d.description ILIKE '%panic%')
      AND d.description NOT ILIKE '%porn%' AND d.description NOT ILIKE '%performance anxiety%' AND d.description NOT ILIKE '%sexual%'),
  b AS (SELECT b0.*, TO_CHAR(DATE_TRUNC('week',dt),'YYYY-MM-DD') wk, lw.lwk,
      CASE WHEN mh.ap IS NOT NULL THEN 'MH' WHEN diag_cat='STI' THEN 'STI' WHEN diag_cat IN ('ED+','PE+','ED+PE+','NSSD') THEN 'SH' ELSE 'Other' END topcat
    FROM b0 LEFT JOIN lw ON lw.ph=b0.phone_no LEFT JOIN mh ON mh.ap=b0.appointment_id)
  SELECT city, locality, wk, COUNT(*) booked, SUM(CASE WHEN st='COMPLETED' THEN 1 ELSE 0 END) done,
    SUM(CASE WHEN (phone_rank IS NULL OR phone_rank<=1) AND lwk=DATE_TRUNC('week',dt) THEN 1 ELSE 0 END) new_tw,
    SUM(CASE WHEN (phone_rank IS NULL OR phone_rank<=1) AND (lwk IS NULL OR lwk<>DATE_TRUNC('week',dt)) THEN 1 ELSE 0 END) new_old,
    SUM(CASE WHEN phone_rank>1 AND COALESCE(prior_done,0)=0 THEN 1 ELSE 0 END) rebook,
    SUM(CASE WHEN phone_rank>1 AND COALESCE(prior_done,0)>0 THEN 1 ELSE 0 END) relapse,
    SUM(CASE WHEN st='COMPLETED' AND topcat='SH' THEN 1 ELSE 0 END) d_sh,
    SUM(CASE WHEN st='COMPLETED' AND topcat='STI' THEN 1 ELSE 0 END) d_sti,
    SUM(CASE WHEN st='COMPLETED' AND topcat='MH' THEN 1 ELSE 0 END) d_mh,
    SUM(CASE WHEN st='COMPLETED' AND topcat='Other' THEN 1 ELSE 0 END) d_oth,
    SUM(CASE WHEN EXTRACT(dow FROM dt) NOT IN (0,6) THEN 1 ELSE 0 END) bkwd,
    SUM(CASE WHEN EXTRACT(dow FROM dt) IN (0,6) THEN 1 ELSE 0 END) bkwe
  FROM b WHERE wk>='{LO}' GROUP BY 1,2,3"""):
    if len(r)>=15 and r[2] in idx:
        e=bk.setdefault(K(r[0],r[1]),{k:Z() for k in ['booked','done','new_tw','new_old','rebook','relapse','sh','sti','mh','oth','bkwd','bkwe']})
        i=idx[r[2]]; v=[int(x) for x in r[3:15]]
        for j,k in enumerate(['booked','done','new_tw','new_old','rebook','relapse','sh','sti','mh','oth','bkwd','bkwe']): e[k][i]=v[j]

def rate(num,den): return [round(num[i]/den[i],1) if den[i] else None for i in range(N)]
out={'weeks':WEEKS,'week_labels':WK_LABELS,'clinics':{}}
for slug,c in L0['clinics'].items():
    loc=c['disp'].split(' · ')[0]; k=K(c['city'],loc)
    av=avail.get(k,{'wd':Z(),'we':Z(),'hr':[0.0]*N,'ahr':[0.0]*N}); adays=[av['wd'][i]+av['we'][i] for i in range(N)]
    lm=leadmap.get(loc.strip().lower(),{'tot':Z(),'src':{}}); leads=lm['tot']
    b=bk.get(k)
    if not b: b={x:Z() for x in ['booked','done','new_tw','new_old','rebook','relapse','sh','sti','mh','oth','bkwd','bkwe']}
    booked=b['booked']; done=b['done']; newp=[b['new_tw'][i]+b['new_old'][i] for i in range(N)]
    out['clinics'][slug]={'disp':c['disp'],'city':c['city'],'loc':loc,
        'availability':{'active_days':adays,'wday_days':av['wd'],'wend_days':av['we'],'hours':av['hr'],'avail_hours':av['ahr']},
        'demand':{'leads':leads,'by_channel':{s:lm['src'][s] for s in lm['src'] if sum(lm['src'][s])>0},'has_leads':sum(leads)>0,
            'lead_book_pct':[round(100*newp[i]/leads[i]) if leads[i] else None for i in range(N)]},
        'bookings':{'total':booked,'new_tw':b['new_tw'],'new_old':b['new_old'],'rebook':b['rebook'],'relapse':b['relapse']},
        'done':{'booked':booked,'done':done,'book_done_pct':[round(100*done[i]/booked[i]) if booked[i] else None for i in range(N)],
            'by_cat':{'SH':b['sh'],'STI':b['sti'],'MH':b['mh'],'Other':b['oth']}},
        'velocity':{'bookings':booked,'wday_days':av['wd'],'wend_days':av['we'],'bk_wday':b['bkwd'],'bk_wend':b['bkwe'],
            'per_active_day':rate(booked,adays),'per_weekday':rate(b['bkwd'],av['wd']),'per_weekend':rate(b['bkwe'],av['we'])},
    }
tb=sum(sum(c['bookings']['total']) for c in out['clinics'].values())
if tb==0:
    print('ABORT: 0 bookings across all clinics (SSO expired / query failed) — NOT writing, keeping existing data.'); raise SystemExit(1)
json.dump(out,open(os.path.join(ROOT,'data_weekly_diag.json'),'w'),separators=(',',':'))
print('wrote data_weekly_diag.json ·',len(out['clinics']),'clinics ·',N,'wk · total bookings',tb)
