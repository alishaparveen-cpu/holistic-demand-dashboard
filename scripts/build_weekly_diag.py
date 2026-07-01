#!/usr/bin/env python3
"""Weekly Diagnostic — per-clinic top-down funnel (Availability → Demand → Conversion → Velocity)
for the 'earliest broken stage' RCA view. Reuses data_clinic_funnels.json (demand/conversion/velocity,
14 weekly) and pulls Availability (active days + roster hours) from roster_slots. One-clinic prototype
(indiranagar); extend CLINICS to scale. Run: AWS_PROFILE=redshift-data python3 scripts/build_weekly_diag.py"""
import os, json, subprocess
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def q(sql):
    out=subprocess.run(['python3',os.path.join(ROOT,'scripts','redshift_query.py')],input=sql,capture_output=True,text=True).stdout
    return [l.split('\t') for l in out.splitlines() if l.strip()]

SRC=json.load(open(os.path.join(ROOT,'data_clinic_funnels.json')))
WEEKS=SRC['weeks']; WK_LABELS=SRC['week_labels']; idx={w:i for i,w in enumerate(WEEKS)}; NW=len(WEEKS)
LO=WEEKS[0]; HI='2026-06-29'
SC_ROSTER_TYPE='cd02525c-1528-4047-a12c-1ad526c28c9a'
CLINICS=['indiranagar']   # prototype; add more slugs to scale

# club by_source into headline channels for the Demand stage
def channels(bysrc):
    g=lambda *ks:[sum((bysrc.get(k,[0]*NW)[i]) for k in ks) for i in range(NW)]
    return {
        'GMB + Google': g('GMB call','GMB web','Google call','Google web'),
        'Practo': g('Practo'),
        'Organic': g('Organic call','Organic web · clinic','Organic web · blog','Organic web · sexologist','Organic web · STI-test','Organic web · doctors','Organic web · home','Organic web · other'),
        'WhatsApp': g('WhatsApp'),
        'Meta': g('Meta'),
    }

def avail(loc):
    ad=[0]*NW; hr=[0.0]*NW
    for r in q(f"""SELECT TO_CHAR(DATE_TRUNC('week', rs.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') wk,
        COUNT(DISTINCT DATE(rs.start_time + INTERVAL '5.5 hours')) adays,
        ROUND(SUM(DATEDIFF(minute, rs.start_time, rs.end_time))/60.0,1) hrs
      FROM allo_consultations.roster_slots rs
      JOIN allo_health.locations loc ON loc.id=rs.location_id AND loc.locality='{loc}' AND loc.deleted_at IS NULL
      WHERE rs.type_id='{SC_ROSTER_TYPE}' AND rs.start_time>='{LO}' AND rs.start_time<'{HI}'
      GROUP BY 1"""):
        if len(r)>=3 and r[0] in idx:
            i=idx[r[0]]; ad[i]=int(r[1]); hr[i]=float(r[2])
    return ad,hr

out={'weeks':WEEKS,'week_labels':WK_LABELS,'clinics':{}}
for slug in CLINICS:
    c=SRC['clinics'].get(slug)
    if not c: print('  skip',slug); continue
    L=c['leads']; B=c['bookings']
    booked=B.get('all_booked',B['total']); done=B.get('all_booked_done',B['done'])
    lead_book=[L['booked_same'][i]+L['booked_later'][i] for i in range(NW)]
    ad,hr=avail(c['loc'])
    out['clinics'][slug]={
        'disp':c['disp'] if 'disp' in c else (c['loc']+' · '+c['city']),'city':c['city'],'loc':c['loc'],
        'availability':{'active_days':ad,'hours':hr},
        'demand':{'leads':L['total'],'by_channel':channels(L['by_source'])},
        'conversion':{'booked':booked,'done':done,
            'lead_book_pct':[round(100*lead_book[i]/L['total'][i]) if L['total'][i] else None for i in range(NW)],
            'book_done_pct':[round(100*done[i]/booked[i]) if booked[i] else None for i in range(NW)]},
        'velocity':{'bookings':booked,
            'per_active_day':[round(booked[i]/ad[i],1) if ad[i] else None for i in range(NW)]},
        'done_by_diag':B.get('done_by_diag',{}),
    }
    print('  built %-12s avail_days=%s'%(slug,sum(ad)))
json.dump(out,open(os.path.join(ROOT,'data_weekly_diag.json'),'w'),separators=(',',':'))
print('wrote data_weekly_diag.json ·',len(out['clinics']),'clinic(s)')
