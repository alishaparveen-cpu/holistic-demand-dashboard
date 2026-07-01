#!/usr/bin/env python3
"""Coimbatore (Bharathi Nagar) WEEKLY funnel — validated lead-journey, WoW.
LEAD side (per week, unique patient at first-relevant-lead week):
  leads by source -> booked SAME week / booked LATER (carryover) / NOT booked.
BOOK side (per week, unique patient first screening call):
  bookings by source  AND  by timing: from THIS-week lead / from PRIOR lead (carry-in) /
  WEB-online (no call lead) / WALK-IN (no lead at all)  -> DONE.
Channel = exophone raw source (GMB/Google/Organic). Calls = clinic own numbers (by number);
web = latest lead source. Writes data_coimbatore_funnel.json.
Run: AWS_PROFILE=redshift-data python3 scripts/build_coimbatore_funnel.py
"""
import os, sys, json, subprocess
from collections import defaultdict, Counter
import openpyxl
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def q(sql): return [l.split('\t') for l in subprocess.run(['python3',os.path.join(ROOT,'scripts','redshift_query.py')],input=sql,capture_output=True,text=True).stdout.splitlines() if l.strip()]
REL="'TALK_TO_DOCTOR','TALK_TO_THERAPIST','NEEDS_TESTS','NEEDS_MEDS','BOOK_APPOINTMENT','BOOK_TEST','BOOK_SLOT'"
OWN={'4440114608':'GMB','4440114631':'Google','4440116568':'Organic'}
LOC='Bharathi Nagar'
# 10 IST-Monday weeks (week-start dates); newest = 22-28 Jun
WEEKS=['2026-04-20','2026-04-27','2026-05-04','2026-05-11','2026-05-18','2026-05-25','2026-06-01','2026-06-08','2026-06-15','2026-06-22']
idx={w:i for i,w in enumerate(WEEKS)}; NW=len(WEEKS); LO=WEEKS[0]; HI='2026-06-29'
def Z(): return [0]*NW
MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
def wlabel(ws):
    y,m,d=map(int,ws.split('-')); import datetime; s=datetime.date(y,m,d); e=s+datetime.timedelta(days=6)
    return ('%d %s'%(s.day,MON[s.month-1])) + '–' + ('%d %s'%(e.day,MON[e.month-1]) if e.month!=s.month else '%d %s'%(e.day,MON[s.month-1]))
WK="TO_CHAR(DATE_TRUNC('week', %s + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD')"

wb=openpyxl.load_workbook(os.path.expanduser('~/Downloads/exophone_categorisation.xlsx'),read_only=True)
ws=wb['All Numbers']; rows=list(ws.iter_rows(values_only=True)); h={c:i for i,c in enumerate(rows[0])}
def chan(raw):
    r=(raw or '').lower()
    if 'gmb' in r: return 'GMB'
    if 'google' in r: return 'Google'
    if 'organic' in r: return 'Organic'
    if r=='practo': return 'Practo'
    if r in ('fb','ig','meta'): return 'Meta'
    return 'Other'
EXO={str(r[h['Exotel Number']] or '').strip():chan(r[h['Raw Source']]) for r in rows[1:] if r[h['Exotel Number']]}

def main():
    # 1) own-number calls per (patient, week): channel(by most-called own #) + relevant flag
    callwk=defaultdict(lambda: defaultdict(lambda:{'nc':0,'rel':0}))  # ph -> wk -> {nc,rel}
    for r in q(f"""SELECT RIGHT(ec."from",10) ph, RIGHT(ec.exotel_number,10) num, {WK%'ec.start_time'} w,
      COUNT(*) nc, SUM(CASE WHEN ca.analysis.user_intent.result::varchar IN ({REL}) AND COALESCE(ca.analysis.patient_intent_strength.result::varchar,'')<>'NOT_A_PATIENT' THEN 1 ELSE 0 END) nrel
      FROM allo_vendors.exotel_calls ec LEFT JOIN allo_analytics.call_analyses ca ON ca.call_id=ec.call_id AND ca.deleted_at IS NULL
      WHERE ec.direction='inbound' AND ec.routed_to='lead_to_call' AND RIGHT(ec.exotel_number,10) IN ('4440114608','4440114631','4440116568')
       AND ec.start_time>='{LO}' AND ec.start_time<'{HI}' GROUP BY 1,2,3"""):
        if len(r)<5 or r[2] not in idx: continue
        ph,num,w,nc,nrel=r[0],r[1],r[2],int(r[3]),int(r[4])
        c=callwk[ph][w]; c['nc']+=nc; c['rel']+=nrel; c.setdefault('bynum',Counter())[num]+=nc
    # collapse to per-(ph,wk): channel + relevant + total calls
    pcw={}  # (ph,wk) -> (channel, rel_bool, ncalls)
    for ph,wks in callwk.items():
        for w,c in wks.items():
            primary=c['bynum'].most_common(1)[0][0]
            pcw[(ph,w)]=(OWN[primary], c['rel']>0, c['nc'])
    # 2) GMB/Organic web leads per (patient, week)
    webwk={}  # (ph,wk) -> source
    for r in q(f"""SELECT RIGHT(phone_no,10) ph, {WK%'created_at'} w FROM allo_persons.lead
      WHERE deleted_at IS NULL AND LOWER(utm_source)='gmb' AND LOWER(utm_medium)='listing'
        AND LOWER(utm_campaign) IN ('bharathi-nagar-clinic-gmb','coimbatore-clinic-gmb')
        AND created_at>='{LO}' AND created_at<'{HI}'"""):
        if len(r)>=2 and r[1] in idx and len(r[0])>=10: webwk[(r[0],r[1])]='GMB web'
    for r in q(f"""SELECT RIGHT(phone_no,10) ph, {WK%'created_at'} w FROM allo_persons.lead
      WHERE deleted_at IS NULL AND LOWER(utm_source)='organic'
        AND (LOWER(utm_campaign) LIKE '%coimbatore%' OR LOWER(utm_campaign) LIKE '%bharathi%')
        AND created_at>='{LO}' AND created_at<'{HI}'"""):
        if len(r)>=2 and r[1] in idx and len(r[0])>=10 and (r[0],r[1]) not in webwk: webwk[(r[0],r[1])]='Organic web'
    # 3) bookings: first SC per patient -> (week, done)
    bk={}
    for r in q(f"""SELECT RIGHT(p.phone_no,10) ph, {WK%'MIN(a.created_at)'} bw,
      MAX(CASE WHEN a.status='COMPLETED' THEN 1 ELSE 0 END) done
      FROM allo_consultations.appointments a JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
      JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.locality='{LOC}' AND loc.deleted_at IS NULL
      JOIN allo_persons.patient p ON p.id=a.patient_id WHERE a.deleted_at IS NULL AND a.created_at>='{LO}' GROUP BY 1"""):
        if len(r)>=3 and r[1] in idx: bk[r[0]]=(r[1],int(r[2]))
    bphs="','".join(bk)
    # NEW acquisition vs RETURNING: is the window screening call the patient's FIRST-EVER appointment?
    # (new = booking_rank 1 AND that rank-1 appt is the SC). returning = had any earlier appointment.
    returning=set()
    for r in q(f"""WITH winsc AS (
        SELECT RIGHT(p.phone_no,10) ph, MIN(a.created_at) scwin
        FROM allo_consultations.appointments a JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
        JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.locality='{LOC}' AND loc.deleted_at IS NULL
        JOIN allo_persons.patient p ON p.id=a.patient_id WHERE a.deleted_at IS NULL AND a.created_at>='{LO}' GROUP BY 1),
      fe AS (SELECT RIGHT(p.phone_no,10) ph, MIN(a.created_at) firstever
        FROM allo_consultations.appointments a JOIN allo_persons.patient p ON p.id=a.patient_id WHERE a.deleted_at IS NULL GROUP BY 1)
      SELECT winsc.ph FROM winsc JOIN fe ON fe.ph=winsc.ph WHERE fe.firstever < winsc.scwin"""):
        if r and r[0]: returning.add(r[0])
    print('  returning (re-booking SC, -> booking-level only): %d / %d total'%(len(returning),len(bk)))
    # 4) web source (latest lead) for booking patients
    lead={}
    for r in q(f"""SELECT ph,origin,src,med,fb,cwk FROM (
      SELECT RIGHT(phone_no,10) ph, origin, LOWER(utm_source) src, LOWER(utm_medium) med,
        CASE WHEN fbclid<>'' THEN 1 ELSE 0 END fb, {WK%'created_at'} cwk,
        ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY created_at DESC) rn
      FROM allo_persons.lead WHERE deleted_at IS NULL AND RIGHT(phone_no,10) IN ('{bphs}') AND created_at>=DATEADD(month,-6,GETDATE())) z WHERE rn=1"""):
        if len(r)>=6: lead[r[0]]=(r[1],r[2],r[3],int(r[4]),r[5])
    def websrc(ph):
        if ph not in lead: return 'Walk-in (no lead)'
        o,s,m,fb,cwk=lead[ph]
        if fb or s in ('fb','facebook','instagram','ig'): return 'Meta'
        if s=='google': return 'Google web'
        if o=='practo' or s=='practo': return 'Practo'
        if s=='gmb': return 'GMB web'
        if o=='whatsapp' or m=='whatsapp': return 'WhatsApp'
        if s=='organic' or o=='exotel': return 'Organic web'
        return 'Direct / no-utm'

    # ===== Practo leads (clinic-specific, from the Practo sheet): (ph, week) =====
    practowk={}
    try:
        sys.path.insert(0,os.path.join(ROOT,'scripts')); import build_source_recon as SR
        by_loc,_=SR.load_practo_sheet()
        locs=['Bharathi Nagar']+(SR.PRACTO_ALIAS.get('Bharathi Nagar',[]) if hasattr(SR,'PRACTO_ALIAS') else [])
        for pl in locs:
            for tup in by_loc.get(pl,set()):
                wk,ph=tup[0],tup[1]
                if wk in idx and len(str(ph))>=10: practowk[(str(ph)[-10:],wk)]='Practo'
        print('  practo leads (Bharathi, in-window):',len(practowk))
    except Exception as e:
        print('  [warn] practo sheet load failed:',str(e)[:120])

    # ===== per-patient: EARLIEST trackable lead -> (week, source). Tie: call > web > practo =====
    touches=defaultdict(list)   # ph -> [(week_idx, week, source, priority)]
    for (ph,w),(c,rel,nc) in pcw.items():
        if rel: touches[ph].append((idx[w],w,c+' call',0))
    for (ph,w),s in webwk.items():   touches[ph].append((idx[w],w,s,1))
    for (ph,w),s in practowk.items():touches[ph].append((idx[w],w,'Practo',2))
    lead_inst={}
    for ph,ts in touches.items():
        ts.sort(key=lambda x:(x[0],x[3])); lead_inst[ph]=(ts[0][1],ts[0][2])

    LEAD_SRC=['GMB call','Google call','Organic call','GMB web','Organic web','Practo']
    leads={'by_source':{s:Z() for s in LEAD_SRC},'total':Z(),'booked_same':Z(),'booked_later':Z(),'not_booked':Z()}
    for ph,(w,src) in lead_inst.items():
        if ph in returning: continue       # returning patients are NOT new demand -> excluded from leads
        i=idx[w]; leads['by_source'].setdefault(src,Z())[i]+=1; leads['total'][i]+=1
        b=bk.get(ph)
        if b and b[0]==w: leads['booked_same'][i]+=1
        elif b and idx[b[0]]>i: leads['booked_later'][i]+=1
        else: leads['not_booked'][i]+=1   # never booked, or booked only earlier

    # ===== bookings FLOW: NEW acquisitions -> this-week / prior / walk-in ; RETURNING -> own slice =====
    def other_source(ph):                 # bookings with NO relevant lead_to_call lead -> web/marketplace/walk-in only
        return websrc(ph)                 # b2p / non-lead-routed calls are NOT a source (not lead-gen)
    FLOW={'thisweek':{}, 'prior':{}, 'other':{}, 'returning':{}}
    ft={'thisweek':Z(),'prior':Z(),'other':Z(),'returning':Z()}
    bookings={'total':Z(),'done':Z()}
    for ph,(bw,done) in bk.items():
        i=idx[bw]; bookings['total'][i]+=1
        if done: bookings['done'][i]+=1
        if ph in returning:               # existing patient re-booking a new SC -> booking-level only
            li=lead_inst.get(ph); src=li[1] if li else other_source(ph)
            FLOW['returning'].setdefault(src,Z())[i]+=1; ft['returning'][i]+=1; continue
        li=lead_inst.get(ph)              # (first relevant-lead week, source)
        if   li and idx[li[0]]==i: bucket='thisweek'; src=li[1]
        elif li and idx[li[0]]<i:  bucket='prior';    src=li[1]
        elif li:                   bucket='thisweek'; src=li[1]   # lead logged after booking (rare)
        else:
            src=other_source(ph)
            if src in ('Walk-in (no lead)','Direct / no-utm'):
                bucket='other'                                   # genuinely no attributable lead
            elif src=='Practo':
                bucket='prior'                                   # Practo booking w/o dated sheet lead -> carry-in
            else:                                                # WEB lead: date by lead-creation week (backtracked)
                cwk=lead[ph][4] if ph in lead else None
                bucket='thisweek' if (cwk in idx and idx[cwk]==i) else 'prior'
        FLOW[bucket].setdefault(src,Z())[i]+=1; ft[bucket][i]+=1
    bookings['flow']={k:{'total':ft[k],'by_source':FLOW[k]} for k in FLOW}

    # ===== merge WEB converted leads into the main leads table (dated at LEAD-CREATION week) =====
    # Web/ad leads are only clinic-knowable once they book -> converted-only (never contribute to "didn't book").
    web_older=0
    for ph,(bw,done) in bk.items():
        if lead_inst.get(ph) or ph in returning: continue    # tracked lead, or returning (not new demand)
        s=other_source(ph)
        if s in ('Walk-in (no lead)','Direct / no-utm','Practo','GMB web'): continue
        cwk=lead[ph][4] if ph in lead else None
        if cwk not in idx: web_older+=1; continue            # web lead created before the 10-wk window
        i=idx[cwk]; leads['by_source'].setdefault(s,Z())[i]+=1; leads['total'][i]+=1
        if idx[bw]>i: leads['booked_later'][i]+=1
        else: leads['booked_same'][i]+=1
    leads['web_older']=web_older
    leads['web_sources']=['Meta','Google web','Organic web','WhatsApp']  # flagged converted-only in UI
    CALLNUM={OWN[n]+' call':n for n in OWN}                   # 'GMB call'->'4440114608' (shown in brackets)

    out={'clinic':'Bharathi Nagar','city':'Coimbatore','weeks':WEEKS,'week_labels':[wlabel(w) for w in WEEKS],
         'lead_sources':LEAD_SRC,'call_numbers':CALLNUM,'leads':leads,'bookings':bookings,
         'note':'Unique-patient WoW screening-call flow. DEMAND = new acquisitions only (the window SC is the patient\'s first-ever appointment, i.e. booking-rank 1 = SC). Returning patients (had an earlier appointment) are excluded from demand and shown only at booking level (④). Leads show ALL sources by channel; web/ad channels (Meta · Google-web · Organic-web · WhatsApp) are converted-only, dated at lead-creation week. Bookings flow: ① this-week lead → ② carry-in → ③ direct/walk-in → ④ returning (repeat SC).'}
    p=os.path.join(ROOT,'data_coimbatore_funnel.json'); json.dump(out,open(p,'w'),separators=(',',':'))
    print('wrote',p)
    F=bookings['flow']
    print('books/wk :',bookings['total'],' done:',bookings['done'])
    print('flow this:',F['thisweek']['total'])
    print('flow prio:',F['prior']['total'])
    print('flow othr:',F['other']['total'])

if __name__=='__main__': main()
