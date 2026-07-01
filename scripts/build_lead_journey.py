#!/usr/bin/env python3
"""LEAD JOURNEY builder (one clinic first). Reconciles, per week, at UNIQUE-PATIENT
SCREENING-CALL level:
  LEADS (by resolved channel, how attributed) -> BOOKED -> every booking decomposed to a
  source (tracked clinic lead this-week / carry-in / resolved-via-lead-table: WhatsApp /
  Assessment / Meta / Google-web / walk-in-no-lead / AI-miss) -> DONE.
Channel certainty: call = dialed Exotel number -> exophone map; web = campaign; practo = sheet.
Untracked bookings are RESOLVED by joining the patient to allo_persons.lead (origin+utm).
Usage: AWS_PROFILE=redshift-data python3 scripts/build_lead_journey.py --clinic bharathi
"""
import os,sys,json,subprocess,argparse,re
sys.path.insert(0,os.path.dirname(__file__))
import build_source_recon as SR
REL=SR.REL; idx=SR.idx; WEEKS=SR.WEEKS
import openpyxl
_wb=openpyxl.load_workbook('/Users/alishaparveen/Downloads/exophone_categorisation.xlsx',read_only=True)
_ws=_wb['All Numbers']; _rows=list(_ws.iter_rows(values_only=True)); _h={c:i for i,c in enumerate(_rows[0])}
EXO={str(r[_h['Exotel Number']] or '').strip():str(r[_h['Category']]) for r in _rows[1:] if r[_h['Exotel Number']]}

def q(sql): return [l.split('\t') for l in subprocess.run(['python3',os.path.join(SR.ROOT,'scripts','redshift_query.py')],input=sql,capture_output=True,text=True).stdout.splitlines() if l.strip()]
def wk(col): return "TO_CHAR(DATE_TRUNC('week', %s + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD')"%col
DATE=re.compile(r'^202\d-\d\d-\d\d$')

# exophone number -> channel for the chosen clinic (from exophone_categorisation.xlsx); city/loc for bookings
CLINICS={
 'bharathi':{'disp':'Bharathi Nagar · Coimbatore','city':'Coimbatore','loc':'Bharathi Nagar',
   'nums':{'4440114608':'GMB call','4440114631':'Google paid call','4440116568':'Organic call'},
   'gmbweb':['bharathi-nagar-clinic-gmb','coimbatore-clinic-gmb']},
}

def resolve_leadsrc(origin,src,med,flow,fbclid,gclid):
    o=(origin or '').lower(); s=(src or '').lower(); m=(med or '').lower(); f=(flow or '').lower()
    if (fbclid and str(fbclid).strip()) or s in ('fb','facebook','instagram','ig'): return 'Meta (FB/IG)'
    if (gclid and str(gclid).strip()) or s=='google' or m=='cpc': return 'Google web'
    if o=='whatsapp' or m=='whatsapp': return 'WhatsApp'
    if o=='practo' or s=='practo': return 'Practo'
    if s=='gmb' and m=='listing': return 'GMB web'
    if f=='assessment': return 'Assessment (organic)'
    return 'Direct / organic'

def run(key, lo='2026-05-18'):
    c=CLINICS[key]; nums="','".join(c['nums']); city=c['city'].replace("'","''"); loc=c['loc'].replace("'","''")
    # 1) all inbound lead calls on this clinic's numbers (relevant + category), per call
    calls=q(f"""SELECT RIGHT(ec."from",10) ph, RIGHT(ec.exotel_number,10) num, {wk('ec.start_time')} w,
      CASE WHEN ca.analysis.user_intent.result::varchar IN ({REL}) AND COALESCE(ca.analysis.patient_intent_strength.result::varchar,'')<>'NOT_A_PATIENT' THEN 1 ELSE 0 END rel,
      ec.start_time st FROM allo_vendors.exotel_calls ec
      LEFT JOIN allo_analytics.call_analyses ca ON ca.call_id=ec.call_id AND ca.deleted_at IS NULL
      WHERE ec.routed_to='lead_to_call' AND ec.direction='inbound' AND RIGHT(ec.exotel_number,10) IN ('{nums}')
        AND ec.start_time>='{lo}' AND ec.start_time<'2026-06-29'""")
    # 2) screening-call bookings at this clinic (first SC per patient + done + book week)
    books=q(f"""SELECT RIGHT(p.phone_no,10) ph, {wk('MIN(a.created_at)')} bw,
      MAX(CASE WHEN a.status='COMPLETED' THEN 1 ELSE 0 END) done
      FROM allo_consultations.appointments a JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
      JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.city='{city}' AND loc.locality='{loc}' AND loc.deleted_at IS NULL
      JOIN allo_persons.patient p ON p.id=a.patient_id WHERE a.deleted_at IS NULL AND a.created_at>='{lo}' GROUP BY 1""")
    bkwk={r[0]:r[1] for r in books if len(r)>=2 and DATE.match(r[1] or '')}
    bkdone={r[0]:int(r[2]) for r in books if len(r)>=3}
    # 3) lead-table resolved source per phone (latest lead) — to resolve untracked bookings
    from collections import defaultdict
    # any-number inbound calls by booking patients (full exophone map) — to source pool/shared-number callers
    bphs="','".join(bkwk.keys())
    anycall=defaultdict(list)
    if bphs:
        for r in q(f"""SELECT RIGHT("from",10) ph, RIGHT(exotel_number,10) num, {wk('start_time')} w
          FROM allo_vendors.exotel_calls WHERE direction='inbound' AND RIGHT("from",10) IN ('{bphs}')
          AND start_time>='{lo}' AND start_time<'2026-06-29'"""):
            if len(r)<3: continue
            ph,num,w=r[0],r[1],r[2]
            if w in idx and num in EXO: anycall[ph].append((w,EXO[num],num))

    leads=q(f"""SELECT ph,origin,src,med,flow,fbclid,gclid FROM (
      SELECT RIGHT(phone_no,10) ph, origin, LOWER(utm_source) src, LOWER(utm_medium) med, user_flow flow,
        fbclid, gclid, ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY created_at DESC) rn
      FROM allo_persons.lead WHERE deleted_at IS NULL AND COALESCE(origin,'')<>'exotel' AND created_at>=DATEADD(month,-6,GETDATE())) z WHERE rn=1""")
    leadsrc={r[0]:resolve_leadsrc(*r[1:7]) for r in leads if len(r)>=7}
    # ---- LEADS side: unique relevant clinic-lead patients per week, by channel ----
    from collections import defaultdict
    pcalls=defaultdict(list)         # ph -> [(wk, channel, number, rel)]
    callbypt={}                       # (ph,wk) -> {rel,chan,num}  (for LEADS dedup)
    for r in calls:
        if len(r)<4: continue
        ph,num,w,rel=r[0],r[1],r[2],int(r[3])
        if w not in idx: continue
        ch=c['nums'].get(num,'Call'); pcalls[ph].append((w,ch,num,rel))
        k=(ph,w)
        if k not in callbypt or (rel and not callbypt[k]['rel']): callbypt[k]={'rel':rel,'chan':ch,'num':num}
    Z=lambda:[0]*len(WEEKS)
    # ---- LEADS: unique RELEVANT patients/week by channel (show number) ----
    leadrows=defaultdict(Z); leadnums=defaultdict(set)
    for (ph,w),v in callbypt.items():
        if v['rel']: leadrows[v['chan']][idx[w]]+=1; leadnums[v['chan']].add(v['num'])
    # ---- BOOKINGS: number-first. every call booking -> its number's channel; relevance = sub-quality ----
    dec=defaultdict(Z); done=defaultdict(Z); subq=defaultdict(lambda:{'rel':0,'miss':0}); decnums=defaultdict(set)
    for ph,bw in bkwk.items():
        if bw not in idx: continue
        i=idx[bw]; d=bkdone.get(ph,0)
        pc=[t for t in pcalls.get(ph,[]) if t[0]<=bw]      # inbound clinic calls at/before booking
        if pc:
            pc.sort(key=lambda x:x[0],reverse=True); w,ch,num,rel=pc[0]   # nearest call to booking
            b='CALL · '+ch; decnums[b].add(num); subq[b]['rel' if rel else 'miss']+=1
        elif ph in leadsrc:
            b='WEB/online · '+leadsrc[ph]
        else:
            ac=[t for t in anycall.get(ph,[]) if t[0]<=bw]
            if ac:
                ac.sort(key=lambda x:x[0],reverse=True); _,cat,num=ac[0]
                b='CALL · %s (shared/pool #)'%cat; decnums[b].add(num); subq[b]['miss']+=1
            else:
                b='untraced (no call, no lead)'
        dec[b][i]+=1
        if d: done[b][i]+=1
    return c,leadrows,leadnums,dec,done,subq,decnums

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--clinic',default='bharathi');a=ap.parse_args()
    c,leadrows,leadnums,dec,done,subq,decnums=run(a.clinic)
    def s4(arr): return sum(arr[:6])  # last 6 weeks total
    print('=== %s · LEAD JOURNEY (last 6 weeks) ===\n'%c['disp'])
    print('① LEADS — unique relevant patients, by channel (attribution = dialed number → exophone map):')
    tl=0
    for ch,arr in sorted(leadrows.items(),key=lambda x:-s4(x[1])): print('   %-20s %4d   (number(s): %s)'%(ch,s4(arr),', '.join(sorted(leadnums[ch])))); tl+=s4(arr)
    print('   %-22s %4d'%('TOTAL clinic leads',tl))
    print('\n② → ⑤ ALL screening-call BOOKINGS at clinic, decomposed (reconciles to total):')
    tb=td=0
    for b,arr in sorted(dec.items()):
        extra=''
        if b in decnums: extra=' · #%s · [relevant %d / AI-missed %d]'%(','.join(sorted(decnums[b])),subq[b]['rel'],subq[b]['miss'])
        print('   %-34s %4d (done %d)%s'%(b,s4(arr),s4(done[b]),extra)); tb+=s4(arr); td+=s4(done[b])
    print('   %-46s %4d  (done %d)'%('TOTAL bookings = leads-booked + carry-in + resolved-gap',tb,td))
