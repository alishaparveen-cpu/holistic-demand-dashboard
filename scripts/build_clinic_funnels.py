#!/usr/bin/env python3
"""NEW validated lead->book WoW funnel (coimbatore-style) for all MH clinics + CALL CATEGORY.
Per clinic: LEADS new-acquisition by channel (+ call-category SH/STI/MH/Other breakdown for a filter);
BOOKINGS flow ① this-week / ② carry-in / ③ direct·walk-in / ④ returning. Only lead_to_call attributes;
GMB/Organic = clinic numbers, Google = clinic paid # (locality-filtered when shared, paid_solo=False).
Writes data_clinic_funnels.json (all clinics, one file). Run: AWS_PROFILE=redshift-data python3 scripts/build_clinic_funnels.py
"""
import os, sys, json, subprocess, datetime
from collections import defaultdict, Counter
import openpyxl
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def q(sql):
    out=subprocess.run(['python3',os.path.join(ROOT,'scripts','redshift_query.py')],input=sql,capture_output=True,text=True).stdout
    return [l.split('\t') for l in out.splitlines() if l.strip()]
REL="'TALK_TO_DOCTOR','TALK_TO_THERAPIST','NEEDS_TESTS','NEEDS_MEDS','BOOK_APPOINTMENT','BOOK_TEST','BOOK_SLOT'"
REL_ORDER=['BOOK_APPOINTMENT','BOOK_SLOT','BOOK_TEST','NEEDS_TESTS','NEEDS_MEDS','TALK_TO_DOCTOR','TALK_TO_THERAPIST']
REL_SET=set(REL_ORDER)   # default-selected intents (the AI-audit relevance gate; strength<>NOT_A_PATIENT also required)
CATMAP={'SEXUAL_HEALTH_GENERAL':'SH','STI':'STI','MENTAL_HEALTH':'MH','OTHER':'Other','NOT_MENTIONED':'Other'}
CATS=['SH','STI','MH','Other']
# DONE-level category = doctor's ACTUAL latest merged-rx diagnosis (not call intent). Precedence STI>SH>MH.
_DX_STI=['genito urinary','genitourinary','post-exposure','post exposure','prophylaxis','syphilis','herpes','gonorr','chlamydia','genital wart','urethritis','trichomon','hpv',' sti',' std']
_DX_SH=['erectile','premature ejacul','low sexual desire','delayed ejacul','sexual dysfunction','compulsive masturbat','porn addict','vaginismus','dyspareunia','anorgasmia','phimosis','nightfall','hypersensitivity','sexual arousal','retrograde ejacul','glans','penile']
_DX_MH=['depress','anxiety','stress','ocd','bipolar','panic','insomnia','adhd',' mood','psychiat','mental health']
def diag_category(descr):
    d=' '+((descr or '').lower())+' '
    if any(k in d for k in _DX_STI): return 'STI'
    if any(k in d for k in _DX_SH): return 'SH'
    if any(k in d for k in _DX_MH): return 'MH'
    return 'Other'   # incl. 'No Symptomatic Sexual Disorder' (screened, no disorder)
# 15 IST-Monday weeks back to the AI call-audit coverage start (~23 Mar); UI defaults to the recent 10, "all" shows these.
WEEKS=['2026-03-23','2026-03-30','2026-04-06','2026-04-13','2026-04-20','2026-04-27','2026-05-04','2026-05-11','2026-05-18','2026-05-25','2026-06-01','2026-06-08','2026-06-15','2026-06-22','2026-06-29']
idx={w:i for i,w in enumerate(WEEKS)}; NW=len(WEEKS); LO=WEEKS[0]; HI='2026-07-06'
DEFAULT_VIEW_WEEKS=10   # UI shows the last N by default
def Z(): return [0]*NW
MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
def wlabel(ws):
    y,m,dd=map(int,ws.split('-')); s=datetime.date(y,m,dd); e=s+datetime.timedelta(days=6)
    return '%d %s–%d %s'%(s.day,MON[s.month-1],e.day,MON[e.month-1])
WK="TO_CHAR(DATE_TRUNC('week', %s + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD')"

wb=openpyxl.load_workbook(os.path.expanduser('~/Downloads/exophone_categorisation.xlsx'),read_only=True)
ws=wb['All Numbers']; xr=list(ws.iter_rows(values_only=True)); xh={c:i for i,c in enumerate(xr[0])}
def chan(raw):
    r=(raw or '').lower()
    if 'gmb' in r: return 'GMB'
    if 'google' in r: return 'Google'
    if 'organic' in r: return 'Organic'
    if r=='practo': return 'Practo'
    if r in ('fb','ig','meta'): return 'Meta'
    return 'Other'
EXO={str(r[xh['Exotel Number']] or '').strip():chan(r[xh['Raw Source']]) for r in xr[1:] if r[xh['Exotel Number']]}

# proven per-clinic configs (from build_mh_funnels). candidate call numbers = gmb + paid; classified by EXO.
RAW={
 'bharathi':   {'disp':'Bharathi Nagar · Coimbatore','city':'Coimbatore','loc':'Bharathi Nagar','nums':['4440114608','4440116568','4440114631'],'paid':'4440114631','paid_solo':True},
 'indiranagar':{'disp':'Indiranagar · Bangalore','city':'Bangalore','loc':'Indiranagar','nums':['8047160881','8047281164','8045680561'],'paid':'8045680561','paid_solo':False},
 'vaishali':   {'disp':'Vaishali Nagar · Jaipur','city':'Jaipur','loc':'Vaishali Nagar','nums':['1414931073','1414931123'],'paid':'1414931123','paid_solo':True},
 'hadapsar':   {'disp':'Hadapsar · Pune','city':'Pune','loc':'Hadapsar','nums':['2241483789','2048556242'],'paid':'2048556242','paid_solo':False},
 'kharghar':   {'disp':'Kharghar · Navi Mumbai','city':'Navi Mumbai','loc':'Kharghar','nums':['2248932451','2248931386'],'paid':'2248931386','paid_solo':False},
 'hubli':      {'disp':'Vidya Nagar · Hubli','city':'Hubli','loc':'Vidya Nagar','nums':['8047094835','8046802123'],'paid':None,'paid_solo':True},
 'kharadi':    {'disp':'Kharadi · Pune','city':'Pune','loc':'Kharadi','nums':['2241484446','2048556242'],'paid':'2048556242','paid_solo':False},
}
def cfg_of(slug):
    c=RAW[slug]; paid=c['paid']
    gmb=sorted({n for n in c['nums'] if EXO.get(n)=='GMB'})
    org=sorted({n for n in c['nums'] if EXO.get(n)=='Organic'})
    google=paid if (paid and EXO.get(paid)=='Google') else None
    return {'slug':slug,'disp':c['disp'],'city':c['city'],'loc':c['loc'],'gmb':gmb,'organic':org,
            'google':google,'google_solo':bool(c['paid_solo'])}

def dispo(phones):
    """latest lead_to_call agent disposition reason per phone (stolen from colleague's lead_disposition)."""
    out={}
    for i in range(0,len(phones),300):
        inlist="','".join(phones[i:i+300])
        for r in q(f"""WITH tk AS (   -- latest lead_to_call task_action per OUR phone (filtered first -> fast)
            SELECT RIGHT(p.phone_no,10) ph, c.id task_action_id,
              ROW_NUMBER() OVER (PARTITION BY RIGHT(p.phone_no,10) ORDER BY a.created_at DESC) rn
            FROM allo_tasks.tasks a
            JOIN allo_tasks.types b ON b.id=a.type_id AND LOWER(b.team)='lead_to_call' AND b.deleted_at IS NULL
            JOIN allo_persons.patient p ON p.id=a.user_id AND RIGHT(p.phone_no,10) IN ('{inlist}')
            JOIN allo_tasks.actions c ON c.task_id=a.id AND c.deleted_at IS NULL
            WHERE a.deleted_at IS NULL AND a.created_at>=DATEADD(day,-150,GETDATE()))
          SELECT tk.ph,
            COALESCE(NULLIF(MAX(CASE WHEN tfa.title='Choose reason' THEN tfa.answer END),''),
                     NULLIF(MAX(CASE WHEN tfa.title='Choose one' AND tfa.field_key='subDisposition' THEN tfa.answer END),''),
                     NULLIF(MAX(CASE WHEN tfa.title='Main Disposition' THEN tfa.answer END),''),'(no tag)') reason
          FROM tk LEFT JOIN allo_tasks.task_form_answers tfa ON tfa.task_action_id=tk.task_action_id AND tfa.deleted_at IS NULL
          WHERE tk.rn=1 GROUP BY tk.ph"""):
            if len(r)>=2 and r[0]: out[r[0]]=r[1]
    return out

def websrc_of(o,s,m,fb,su=''):
    if fb or s in ('fb','facebook','instagram','ig'): return 'Meta'
    if s=='google': return 'Google web'
    if o=='practo' or s=='practo': return 'Practo'
    if s=='gmb': return 'GMB web'
    if o=='whatsapp' or m=='whatsapp': return 'WhatsApp'
    if s=='organic' or o=='exotel':
        su=su or ''
        if 'blog' in su: return 'Organic web · blog'
        if 'sexologist' in su: return 'Organic web · sexologist'
        if 'std' in su or 'testing' in su: return 'Organic web · STI-test'
        if 'doctor' in su: return 'Organic web · doctors'
        if 'clinic' in su: return 'Organic web · clinic'
        if su.rstrip('/').endswith('allohealth.com'): return 'Organic web · home'
        return 'Organic web · other'
    return 'Direct / no-utm'

def clinic_funnel(cfg, booked_at=None):
    booked_at=booked_at or {}
    loc=cfg['loc'].replace("'","''")
    bt={'in':Z(),'out':Z(),'inph':set(),'outph':set()}   # shared-number BACKTRACK weekly moves (deduped per patient)
    pcw={}; catwk={}; callraw={}   # callraw[(channel,ph,w)] = primary AI intent (per-channel, no cross-channel dedup)
    def pull(nums, channel, locf):
        if not nums: return
        inlist="','".join(nums)
        # shared number (locf): pull WITHOUT the AI locality filter, then BACKTRACK per caller by where they booked
        bmsel=(", MAX(ca.analysis.user_intent.locality_mentioned.best_match::varchar) bm") if locf else ""
        for r in q(f"""SELECT RIGHT(ec."from",10) ph, {WK%'ec.start_time'} w, COUNT(*) nc,
          SUM(CASE WHEN ca.analysis.user_intent.result::varchar IN ({REL}) AND COALESCE(ca.analysis.patient_intent_strength.result::varchar,'')<>'NOT_A_PATIENT' THEN 1 ELSE 0 END) nrel,
          LISTAGG(DISTINCT CASE WHEN ca.analysis.user_intent.result::varchar IN ({REL}) THEN ca.analysis.diagnoses.category::varchar END,',') cats,
          LISTAGG(DISTINCT CASE WHEN COALESCE(ca.analysis.patient_intent_strength.result::varchar,'')<>'NOT_A_PATIENT' THEN ca.analysis.user_intent.result::varchar END,',') intents{bmsel}
          FROM allo_vendors.exotel_calls ec LEFT JOIN allo_analytics.call_analyses ca ON ca.call_id=ec.call_id AND ca.deleted_at IS NULL
          WHERE ec.direction='inbound' AND ec.routed_to='lead_to_call' AND RIGHT(ec.exotel_number,10) IN ('{inlist}')
            AND (ec.start_time+INTERVAL '5 hours 30 minutes')>='{LO}' AND (ec.start_time+INTERVAL '5 hours 30 minutes')<'{HI}' GROUP BY 1,2"""):
            if len(r)<4 or r[1] not in idx: continue
            ph,w,nc,nrel=r[0],r[1],int(r[2]),int(r[3]); cats=(r[4] if len(r)>4 else '') or ''
            if locf:                                    # BACKTRACK: shared number → credit the clinic they BOOKED at
                bm=(r[6] if len(r)>6 else None); bset=booked_at.get(ph)
                if bset and loc in bset:
                    if bm!=loc and ph not in bt['inph']: bt['inph'].add(ph); bt['in'][idx[w]]+=1   # booking gives a lead AI-locality missed
                elif bset:                              # booked at another MH clinic → belongs there, not here
                    if bm==loc and ph not in bt['outph']: bt['outph'].add(ph); bt['out'][idx[w]]+=1  # AI-locality credited us, booked elsewhere
                    continue
                else:                                   # never booked → no booking to backtrack, trust AI locality
                    if bm!=loc: continue
            k=(ph,w); prev=pcw.get(k)
            if not prev or nc>prev[2]: pcw[k]=(channel,(nrel>0) or (prev[1] if prev else False),nc)
            elif nrel>0 and not prev[1]: pcw[k]=(prev[0],True,prev[2])
            if nrel>0 and k not in catwk:
                for raw in cats.split(','):
                    if raw and raw!='None': catwk[k]=CATMAP.get(raw,'Other'); break
            ints=[('UNDETERMINED' if x in ('True','true') else x) for x in ((r[5] if len(r)>5 else '') or '').split(',') if x and x!='None']
            callraw[(channel,ph,w)]=next((ri for ri in REL_ORDER if ri in ints),(ints[0] if ints else 'NOT_A_PATIENT'))
    pull(cfg['gmb'],'GMB',False)
    pull([cfg['google']] if cfg['google'] else [],'Google',not cfg['google_solo'])
    pull(cfg['organic'],'Organic',False)
    # a LEAD must be a real patient we can track to a booking -> drop callers with NO patient record
    callphs=list({ph for (ph,w) in pcw})
    haspat=set()
    for i in range(0,len(callphs),400):
        inlist="','".join(callphs[i:i+400])
        for r in q(f"SELECT DISTINCT RIGHT(phone_no,10) FROM allo_persons.patient WHERE deleted_at IS NULL AND RIGHT(phone_no,10) IN ('{inlist}')"):
            if r and r[0]: haspat.add(r[0])
    pcw={k:v for k,v in pcw.items() if k[0] in haspat}
    catwk={k:v for k,v in catwk.items() if k[0] in haspat}
    callraw={k:v for k,v in callraw.items() if k[1] in haspat}   # (channel,ph,w): keep patient-id only
    # per-channel intent breakdown (no cross-channel dedup) -> "all call leads" matching colleague + intent dropdown
    call_intent=defaultdict(lambda: defaultdict(Z))   # channel -> intent -> weekly unique patients
    for (channel,ph,w),prim in callraw.items():
        call_intent[channel][prim][idx[w]]+=1
    # web-listing leads
    webwk={}; locslug=cfg['loc'].strip().lower().replace(' ','-'); cityslug=cfg['city'].strip().lower().replace(' ','-')
    camps="','".join({locslug+'-clinic-gmb',cityslug+'-clinic-gmb'})
    for r in q(f"""SELECT RIGHT(phone_no,10) ph, {WK%'created_at'} w FROM allo_persons.lead
      WHERE deleted_at IS NULL AND LOWER(utm_source)='gmb' AND LOWER(utm_medium)='listing'
        AND LOWER(utm_campaign) IN ('{camps}') AND (created_at+INTERVAL '5 hours 30 minutes')>='{LO}' AND (created_at+INTERVAL '5 hours 30 minutes')<'{HI}'"""):
        if len(r)>=2 and r[1] in idx and len(r[0])>=10: webwk[(r[0],r[1])]='GMB web'
    for r in q(f"""SELECT RIGHT(phone_no,10) ph, {WK%'created_at'} w FROM allo_persons.lead
      WHERE deleted_at IS NULL AND LOWER(utm_source)='organic'
        AND (LOWER(utm_campaign) LIKE '%{cityslug}%' OR LOWER(utm_campaign) LIKE '%{locslug}%')
        AND (created_at+INTERVAL '5 hours 30 minutes')>='{LO}' AND (created_at+INTERVAL '5 hours 30 minutes')<'{HI}'"""):
        if len(r)>=2 and r[1] in idx and len(r[0])>=10 and (r[0],r[1]) not in webwk: webwk[(r[0],r[1])]='Organic web'
    # bookings
    bk={}
    for r in q(f"""SELECT RIGHT(p.phone_no,10) ph, {WK%'MIN(a.created_at)'} bw,
      MAX(CASE WHEN a.status='COMPLETED' THEN 1 ELSE 0 END) done
      FROM allo_consultations.appointments a JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
      JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.locality='{loc}' AND loc.deleted_at IS NULL
      JOIN allo_persons.patient p ON p.id=a.patient_id WHERE a.deleted_at IS NULL AND (a.created_at+INTERVAL '5 hours 30 minutes')>='{LO}' GROUP BY 1"""):
        if len(r)>=3 and r[1] in idx: bk[r[0]]=(r[1],int(r[2]))
    if not bk: return None
    bphs="','".join(bk)
    returning=set()
    for r in q(f"""WITH winsc AS (SELECT RIGHT(p.phone_no,10) ph, MIN(a.created_at) scwin
        FROM allo_consultations.appointments a JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
        JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.locality='{loc}' AND loc.deleted_at IS NULL
        JOIN allo_persons.patient p ON p.id=a.patient_id WHERE a.deleted_at IS NULL AND (a.created_at+INTERVAL '5 hours 30 minutes')>='{LO}' GROUP BY 1),
      fe AS (SELECT RIGHT(p.phone_no,10) ph, MIN(a.created_at) fe FROM allo_consultations.appointments a
        JOIN allo_persons.patient p ON p.id=a.patient_id WHERE a.deleted_at IS NULL GROUP BY 1)
      SELECT winsc.ph FROM winsc JOIN fe ON fe.ph=winsc.ph WHERE fe.fe<winsc.scwin"""):
        if r and r[0]: returning.add(r[0])
    # ALL SC booked per (patient×week) — NOT collapsed to first week — to reproduce "All Booked During the Week"
    allbk={}
    for r in q(f"""SELECT RIGHT(p.phone_no,10) ph, {WK%'a.created_at'} w,
      MAX(CASE WHEN a.status='COMPLETED' THEN 1 ELSE 0 END) done
      FROM allo_consultations.appointments a JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
      JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.locality='{loc}' AND loc.deleted_at IS NULL
      JOIN allo_persons.patient p ON p.id=a.patient_id WHERE a.deleted_at IS NULL AND (a.created_at+INTERVAL '5 hours 30 minutes')>='{LO}' GROUP BY 1,2"""):
        if len(r)>=3 and r[1] in idx: allbk[(r[0],r[1])]=int(r[2])
    # DONE-level category from doctor's LATEST merged-rx diagnosis (clinical truth, not call intent)
    diagcat={}; allphs=list({ph for (ph,w) in allbk})
    for ci in range(0,len(allphs),400):
        inlist="','".join(allphs[ci:ci+400])
        if not inlist: continue
        for r in q(f"""SELECT ph, descr FROM (
          SELECT RIGHT(p.phone_no,10) ph, LISTAGG(DISTINCT diag.description,' | ') descr,
            RANK() OVER (PARTITION BY p.id ORDER BY enc.created_at DESC) rnk
          FROM allo_encounters.encounters enc
          JOIN allo_persons.patient p ON p.id=enc.patient_id AND p.deleted_at IS NULL
          LEFT JOIN allo_observations.diagnoses diag ON diag.encounter_id=enc.id AND diag.deleted_at IS NULL
          WHERE enc.deleted_at IS NULL AND LOWER(enc.type) LIKE '%merged-rx%' AND RIGHT(p.phone_no,10) IN ('{inlist}')
          GROUP BY p.id, RIGHT(p.phone_no,10), enc.id, enc.created_at) z WHERE rnk=1 AND descr IS NOT NULL"""):
            if len(r)>=2 and r[0] and r[0] not in diagcat: diagcat[r[0]]=diag_category(r[1])
    # full SC history at THIS clinic (no window floor) -> first-ever SC week + first COMPLETED SC week
    # → classify each booking as NEW (first-ever) / RE-BOOK (prior SC, none completed) / RELAPSE (prior SC completed)
    fscw={}; fdonew={}
    for ci in range(0,len(allphs),400):
        inlist="','".join(allphs[ci:ci+400])
        if not inlist: continue
        for r in q(f"""SELECT RIGHT(p.phone_no,10) ph,
            DATE_TRUNC('week', MIN(DATEADD(minute,330,a.created_at)))::varchar fscw,
            DATE_TRUNC('week', MIN(CASE WHEN a.status IN ('COMPLETED','RECONSULTED') THEN DATEADD(minute,330,a.created_at) END))::varchar fdonew
          FROM allo_consultations.appointments a
          JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
          JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.locality='{loc}' AND loc.deleted_at IS NULL
          JOIN allo_persons.patient p ON p.id=a.patient_id
          WHERE a.deleted_at IS NULL AND RIGHT(p.phone_no,10) IN ('{inlist}') GROUP BY 1"""):
            if r and r[0]:
                fscw[r[0]]=(r[1] or '')[:10]; fdonew[r[0]]=((r[2] or '')[:10] or None)
    lead={}
    for r in q(f"""SELECT ph,origin,src,med,fb,cwk,su FROM (
      SELECT RIGHT(phone_no,10) ph, origin, LOWER(utm_source) src, LOWER(utm_medium) med,
        CASE WHEN fbclid<>'' THEN 1 ELSE 0 END fb, {WK%'created_at'} cwk, LOWER(REGEXP_SUBSTR(source_url,'^[^?]+')) su,
        ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY created_at DESC) rn
      FROM allo_persons.lead WHERE deleted_at IS NULL AND RIGHT(phone_no,10) IN ('{bphs}') AND created_at>=DATEADD(month,-6,GETDATE())) z WHERE rn=1"""):
        if len(r)>=6: lead[r[0]]=(r[1],r[2],r[3],int(r[4]),r[5],(r[6] if len(r)>6 else ''))
    def other_source(ph):
        if ph not in lead: return 'Walk-in (no lead)'
        e=lead[ph]; return websrc_of(e[0],e[1],e[2],e[3],e[5] if len(e)>5 else '')
    practowk={}
    try:
        sys.path.insert(0,os.path.join(ROOT,'scripts')); import build_source_recon as SR
        by_loc,_=SR.load_practo_sheet()
        locs=[cfg['loc']]+(SR.PRACTO_ALIAS.get(cfg['loc'],[]) if hasattr(SR,'PRACTO_ALIAS') else [])
        for pl in locs:
            for tup in by_loc.get(pl,set()):
                wk,ph=tup[0],tup[1]
                if wk in idx and len(str(ph))>=10: practowk[(str(ph)[-10:],wk)]='Practo'
    except Exception as e: print('   [warn practo]',str(e)[:70])
    # leads
    touches=defaultdict(list)
    for (ph,w),(c,rel,nc) in pcw.items():
        if rel: touches[ph].append((idx[w],w,c+' call',0))
    for (ph,w),s in webwk.items(): touches[ph].append((idx[w],w,s,1))
    for (ph,w),s in practowk.items(): touches[ph].append((idx[w],w,'Practo',2))
    # booked callers the AI marked non-relevant on EVERY call, with no web/practo touch, are still real leads
    # (they booked => proven demand the relevance filter under-captured). Fold them in as call leads.
    covered=set(touches)
    for (ph,w),(c,rel,nc) in pcw.items():
        if (not rel) and (ph in bk) and (ph not in covered):
            touches[ph].append((idx[w],w,c+' call',3,1))   # credit the actual call source (# is known); AI couldn't determine intent but they booked
    lead_inst={}
    for ph,ts in touches.items():
        b=bk.get(ph)
        cand=[t for t in ts if (not b) or t[0]<=idx[b[0]]]   # for bookers, only touches at/before the booking (a call logged AFTER booking didn't convert them)
        if not cand: continue
        cand.sort(key=lambda x:(x[0],x[3])); lead_inst[ph]=(cand[0][1],cand[0][2],cand[0][4] if len(cand[0])>4 else 0)
    LEAD_SRC=['GMB call','Google call','Organic call','GMB web','Organic web','Practo']
    leads={'by_source':{s:Z() for s in LEAD_SRC},'total':Z(),'booked_same':Z(),'booked_later':Z(),'not_booked':Z(),
           'undet_booked':{},'callcat':{c:{} for c in CATS}}
    nobook_wk={}
    for ph,(w,src,undet) in lead_inst.items():
        if ph in returning: continue
        i=idx[w]; leads['by_source'].setdefault(src,Z())[i]+=1; leads['total'][i]+=1
        if undet: leads['undet_booked'].setdefault(src,Z())[i]+=1
        if src.endswith('call'):
            cat=catwk.get((ph,w),'Other')
            leads['callcat'][cat].setdefault(src,Z()); leads['callcat'][cat][src][i]+=1
        b=bk.get(ph)
        if b and b[0]==w: leads['booked_same'][i]+=1
        elif b and idx[b[0]]>i: leads['booked_later'][i]+=1
        else: leads['not_booked'][i]+=1; nobook_wk[ph]=i
    # STOLEN: agent disposition for new leads that didn't book — WEEKLY × reason
    dmap=dispo(list(nobook_wk))
    reason_wk=defaultdict(Z)
    for ph,i in nobook_wk.items():
        reason_wk[dmap.get(ph,'(not yet dispositioned)')][i]+=1
    order=sorted(reason_wk,key=lambda r:-sum(reason_wk[r]))
    leads['nobook_reasons']=[[r,sum(reason_wk[r])] for r in order[:12]]
    leads['nobook_reasons_weekly']={r:reason_wk[r] for r in order[:12]}
    leads['nobook_total']=len(nobook_wk)
    web_older=0
    for ph,(bw,done) in bk.items():
        if lead_inst.get(ph) or ph in returning: continue
        s=other_source(ph)
        if s in ('Walk-in (no lead)','Direct / no-utm','Practo'): continue   # same set bookings dates -> ①==booked_same
        cwk=lead[ph][4] if ph in lead else None
        if cwk not in idx: web_older+=1; continue
        i=idx[cwk]; leads['by_source'].setdefault(s,Z())[i]+=1; leads['total'][i]+=1
        if idx[bw]==i: leads['booked_same'][i]+=1     # booked the same week the web lead was created
        else: leads['booked_later'][i]+=1             # else carry-in (matches bookings ②)
    leads['web_older']=web_older
    # ---- intent transparency + ALL call leads (no cross-channel dedup, = colleague) + bucketed-elsewhere ----
    leads['call_intent']={ch:dict(call_intent[ch]) for ch in call_intent}
    leads['intent_order']=REL_ORDER
    callall={}
    for ch in call_intent:
        callall[ch+' call']=[sum(call_intent[ch][it][i] for it in call_intent[ch] if it in REL_SET) for i in range(NW)]
    leads['call_all']=callall                       # relevant callers per channel, NOT deduped across channels
    bcount=defaultdict(Counter); bphs=defaultdict(list); seen=set()
    for (channel,ph,w),prim in sorted(callraw.items()):
        if prim not in REL_SET: continue
        src=channel+' call'; key=(src,ph)
        if key in seen: continue
        seen.add(key)
        li=lead_inst.get(ph); assigned=li[1] if li else None
        if assigned!=src:                            # relevant caller NOT credited to this channel in the funnel
            dest=(assigned if li else ('returning patient' if ph in returning else 'no patient-lead / not new'))
            bcount[src][dest]+=1
            if len(bphs[src])<20: bphs[src].append((ph,dest))
    allb=list({ph for s in bphs for ph,_ in bphs[s]}); pidm={}
    for i in range(0,len(allb),400):
        inlist="','".join(allb[i:i+400])
        if inlist:
            for r in q(f"SELECT RIGHT(phone_no,10) ph, MAX(id) FROM allo_persons.patient WHERE deleted_at IS NULL AND RIGHT(phone_no,10) IN ('{inlist}') GROUP BY 1"):
                if len(r)>=2: pidm[r[0]]=r[1]
    leads['bucketed']={s:[[d,n] for d,n in bcount[s].most_common()] for s in bcount}
    leads['bucketed_sample']={s:[[pidm.get(ph,'(none)'),'…'+ph[-4:],dest] for ph,dest in bphs[s]] for s in bphs}
    # ---- breakdown of "Other" (non-book-intent) call patients: missed leads? (count · booked · agent reason) ----
    other_phs={}
    for (channel,ph,w),prim in callraw.items():
        if prim not in REL_SET: other_phs.setdefault(ph,prim)
    odisp=dispo(list(other_phs))
    ob=defaultdict(lambda:{'total':0,'booked':0,'reasons':Counter()})
    for ph,prim in other_phs.items():
        e=ob[prim]; e['total']+=1
        if ph in bk: e['booked']+=1
        e['reasons'][odisp.get(ph,'(not yet dispositioned)')]+=1
    leads['other_call_breakdown']={k:{'total':v['total'],'booked':v['booked'],'reasons':[[r,n] for r,n in v['reasons'].most_common(6)]} for k,v in ob.items()}
    # ---- WEEKLY version: each non-book caller placed in their earliest non-book call-week, split by agent-disposition reason ----
    other_wk={}
    for (channel,ph,w),prim in callraw.items():
        if prim not in REL_SET:
            wi=idx[w]
            if ph not in other_wk or wi<other_wk[ph][0]: other_wk[ph]=(wi,prim)
    reason_wkO=defaultdict(Z); booked_wkO=Z(); total_wkO=Z()
    for ph,(wi,prim) in other_wk.items():
        r=odisp.get(ph,'(not yet dispositioned)')
        reason_wkO[r][wi]+=1; total_wkO[wi]+=1
        if ph in bk: booked_wkO[wi]+=1
    ordO=sorted(reason_wkO, key=lambda r:-sum(reason_wkO[r]))
    leads['other_call_weekly']={'reasons':[[r,reason_wkO[r]] for r in ordO],'booked':booked_wkO,'total':total_wkO}
    FLOW={'thisweek':{},'prior':{},'other':{},'returning':{}}; ft={k:Z() for k in FLOW}
    bookings={'total':Z(),'done':Z()}
    for ph,(bw,done) in bk.items():
        i=idx[bw]; bookings['total'][i]+=1
        if done: bookings['done'][i]+=1
        if ph in returning:
            li=lead_inst.get(ph); src=li[1] if li else other_source(ph)
            FLOW['returning'].setdefault(src,Z())[i]+=1; ft['returning'][i]+=1; continue
        li=lead_inst.get(ph)
        if   li and idx[li[0]]==i: bucket='thisweek'; src=li[1]
        elif li and idx[li[0]]<i:  bucket='prior';    src=li[1]
        else:                       # no tracked lead, OR tracked lead logged AFTER booking (not the source)
            src=other_source(ph)
            if src in ('Walk-in (no lead)','Direct / no-utm'): bucket='other'
            elif src=='Practo': bucket='prior'
            else:
                cwk=lead[ph][4] if ph in lead else None
                bucket='thisweek' if (cwk in idx and idx[cwk]==i) else 'prior'
        FLOW[bucket].setdefault(src,Z())[i]+=1; ft[bucket][i]+=1
    bookings['flow']={k:{'total':ft[k],'by_source':FLOW[k]} for k in FLOW}
    # ALL SC booked per week (incl. repeat bookers) + DONE-by-diagnosis (doctor's clinical category)
    ab_total=Z(); ab_done=Z(); done_by_diag={c:Z() for c in CATS}; booked_by_diag={c:Z() for c in CATS}
    for (ph,w),dn in allbk.items():
        i=idx[w]; ab_total[i]+=1; dc=diagcat.get(ph,'Other'); booked_by_diag[dc][i]+=1
        if dn: ab_done[i]+=1; done_by_diag[dc][i]+=1
    bookings['all_booked']=ab_total; bookings['all_booked_done']=ab_done
    bookings['done_by_diag']=done_by_diag; bookings['booked_by_diag']=booked_by_diag
    # ---- CLEAN PARTITION of All-SC-booked (each booking → exactly ONE bucket; no double-count) ----
    # NEW (first-ever SC at clinic): split by lead → this-week / older / not-attributable.  REPEAT: rebook(prior never done) / relapse(prior done).
    TAXK=['new_tw','new_old','new_na','rebook','relapse']
    TAX={k:{} for k in TAXK}; taxt={k:Z() for k in TAXK}
    for (ph,w),dn in allbk.items():
        i=idx[w]; f=fscw.get(ph); dc=fdonew.get(ph)
        if f==w:                                   # first-ever SC at this clinic = NEVER booked before
            li=lead_inst.get(ph)
            if li and idx.get(li[0])==i: b='new_tw'; src=li[1]
            elif li and idx.get(li[0],99)<i: b='new_old'; src=li[1]
            else:
                src=other_source(ph)
                if src in ('Walk-in (no lead)','Direct / no-utm'): b='new_na'          # truly no usable source
                elif src=='Practo': b='new_old'                                        # converted-only → carry-in
                else:                                                                  # web/meta: date at lead creation
                    cwk=lead[ph][4] if ph in lead else None
                    b='new_tw' if (cwk in idx and idx.get(cwk)==i) else 'new_old'
        else:                                      # had an SC before (repeat)
            b='relapse' if (dc and dc<w) else 'rebook'
            li=lead_inst.get(ph); src=li[1] if li else other_source(ph)
        TAX[b].setdefault(src,Z())[i]+=1; taxt[b][i]+=1
    bookings['tax']={k:{'total':taxt[k],'by_source':TAX[k]} for k in TAXK}
    leads['backtrack']={'shared_num':(cfg['google'] if (cfg['google'] and not cfg['google_solo']) else None),
                        'in':bt['in'],'out':bt['out'],'corrected_in':sum(bt['in']),'moved_out':sum(bt['out'])}
    nums={'GMB call':','.join(cfg['gmb']) or '—','Google call':cfg['google'] or '—','Organic call':','.join(cfg['organic']) or '—'}
    return {'disp':cfg['disp'],'city':cfg['city'],'loc':cfg['loc'],'numbers':nums,
            'google_shared':(not cfg['google_solo']) if cfg['google'] else None,'leads':leads,'bookings':bookings}

def main():
    only=sys.argv[1] if len(sys.argv)>1 else None
    out={'weeks':WEEKS,'week_labels':[wlabel(w) for w in WEEKS],'cats':CATS,'default_view_weeks':DEFAULT_VIEW_WEEKS,
         'call_numbers':{'GMB call':'','Google call':'','Organic call':''},'clinics':{}}
    p=os.path.join(ROOT,'data_clinic_funnels.json')
    base=out
    if only and os.path.exists(p):
        try: base=json.load(open(p)); base.update({k:out[k] for k in out if k!='clinics'}); base.setdefault('clinics',{})
        except Exception: base=out
    # GLOBAL: which MH clinic(s) each patient booked an SC at (window) — enables shared-number backtracking
    locs=[cfg_of(s)['loc'] for s in RAW]; inloc="','".join(l.replace("'","''") for l in locs); booked_at={}
    for r in q(f"""SELECT DISTINCT RIGHT(p.phone_no,10) ph, loc.locality
      FROM allo_consultations.appointments a
      JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
      JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.locality IN ('{inloc}') AND loc.deleted_at IS NULL
      JOIN allo_persons.patient p ON p.id=a.patient_id
      WHERE a.deleted_at IS NULL AND (a.created_at+INTERVAL '5 hours 30 minutes')>='{LO}'"""):
        if len(r)>=2 and r[0]: booked_at.setdefault(r[0],set()).add(r[1])
    print('booked_at map: %d patients'%len(booked_at))
    for slug in RAW:
        if only and slug!=only: continue
        cfg=cfg_of(slug)
        print('building %-12s gmb=%s google=%s(solo=%s) org=%s'%(slug,cfg['gmb'],cfg['google'],cfg['google_solo'],cfg['organic']))
        try:
            f=clinic_funnel(cfg, booked_at)
            if f:
                base['clinics'][slug]=f
                print('   ok leads=%d bookings=%d'%(sum(f['leads']['total']),sum(f['bookings']['total'])))
                json.dump(base,open(p,'w'),separators=(',',':'))   # incremental save -> page loads as each clinic finishes
        except Exception as e:
            import traceback; print('   [ERR]',str(e)[:150])
    out=base
    if not out['clinics']:           # guard: never overwrite good data with an empty build (SSO/cluster died)
        print('ABORT: 0 clinics built (SSO expired / cluster paused?) — NOT writing, existing data kept.'); return
    if only and os.path.exists(p):   # merge into existing when building one clinic
        ex=json.load(open(p)); ex.setdefault('clinics',{}).update(out['clinics']); out=ex
    json.dump(out,open(p,'w'),separators=(',',':'))
    print('wrote',p,'·',len(out['clinics']),'clinics')

if __name__=='__main__': main()
