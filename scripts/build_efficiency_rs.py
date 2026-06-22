#!/usr/bin/env python3
"""Redshift-native Channel Efficiency dataset (parallel to the L0-sheet build, for validation).
Volume funnel (leads, lead->book, bookings, done, B2D) straight from Redshift:
  - leads + booked  : production.public.main_source_wise_leads  (the same table the sheet's ETL uses)
  - bookings/done   : data.json weekly_channel (gross, already Redshift-native & matching L0)
  - Google spend    : data_marketing.json
Revenue / verified-leads / Meta+Practo spend are carried from the L0 build for now (flagged),
pending their Redshift sources. Writes data_efficiency_rs.json (same shape as data_efficiency.json)
and prints an RS-vs-L0 comparison so we can spot sheet errors (e.g. the 26-Apr leads bug).
Run: AWS_PROFILE=redshift-data python3 scripts/build_efficiency_rs.py"""
import os, sys, subprocess, json, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def rs(sql):
    p = subprocess.run([sys.executable, os.path.join(ROOT,'scripts','redshift_query.py')], input=sql, capture_output=True, text=True)
    if p.returncode!=0 or 'ERROR' in p.stderr: sys.stderr.write(p.stderr[:300]); sys.exit(1)
    return [l.split('\t') for l in p.stdout.strip().splitlines() if l.strip()]

CH_CASE = """CASE WHEN source='Google' THEN 'google_ad'
  WHEN source='Organic' AND organic_l2 IN ('Google Listing','PC-Inbound') THEN 'gmb'
  WHEN source='Organic' THEN 'organic'
  WHEN source IN ('Fb','Instagram') THEN 'meta'
  WHEN source LIKE 'Practo%' THEN 'practo'
  WHEN source='Justdial' THEN 'justdial' ELSE 'others' END"""

def main():
    # ── leads + booked by channel & week (Monday-start) ──
    rows = rs(f"""SELECT TO_CHAR(DATE(week)::date-6,'YYYY-MM-DD') wk, {CH_CASE} ch,
      COUNT(*) leads, COUNT(call_booking_ts) booked
      FROM production.public.main_source_wise_leads WHERE week>='2026-03-23' GROUP BY 1,2;""")
    weeks = sorted({r[0] for r in rows})                       # oldest-first (Mondays)
    _today = datetime.date.today()                              # keep only FULLY-COMPLETE weeks (week-ending Sunday already past)
    weeks = [w for w in weeks if datetime.date.fromisoformat(w)+datetime.timedelta(days=6) < _today]  # dynamic — never goes stale like the old hardcoded cutoff
    weeks = weeks[-12:]
    idx = {w:i for i,w in enumerate(weeks)}
    CHANS = ['google_ad','gmb','organic','meta','practo','justdial','others']
    lead = {c:[0]*len(weeks) for c in CHANS}; book = {c:[0]*len(weeks) for c in CHANS}
    for wk,ch,l,b in rows:
        if wk in idx and ch in lead:
            lead[ch][idx[wk]] += int(l); book[ch][idx[wk]] += int(b)
    def tot(d): return [sum(d[c][i] for c in CHANS) for i in range(len(weeks))]
    leadsT, bookT = tot(lead), tot(book)
    # gmbgoogle = gmb + google_ad
    for d in (lead,book): d['gmbgoogle']=[d['gmb'][i]+d['google_ad'][i] for i in range(len(weeks))]; d['gsearch']=d['google_ad']

    # ── bookings/done by channel from data.json (gross, matches L0) ──
    dj = json.load(open(os.path.join(ROOT,'data.json')))
    djw = dj['weeks']; A = dj['all']
    def dj_funnel(field): return [ (A['weekly_funnel'].get(w,{}) or {}).get(field,0) for w in weeks ]
    bookingsT = dj_funnel('gross'); doneT = dj_funnel('calls_done')
    # channel bookings/done: data.json weekly_channel keyed by channel name
    CHMAP = {'GMB':'gmb','Google':'gsearch','Practo':'practo','Organic':'organic','Meta':'meta','Others':'others'}
    wc = A.get('weekly_channel',{})
    chBk = {v:[0]*len(weeks) for v in CHMAP.values()}; chDn = {v:[0]*len(weeks) for v in CHMAP.values()}
    for w in weeks:
        cell = wc.get(w,{})
        for nm,key in CHMAP.items():
            d = cell.get(nm,{}) if isinstance(cell,dict) else {}
            chBk[key][idx[w]] = d.get('gross', d.get('bookings',0)) if isinstance(d,dict) else 0
            chDn[key][idx[w]] = d.get('done', d.get('calls_done',0)) if isinstance(d,dict) else 0
    chBk['gmbgoogle']=[chBk['gmb'][i]+chBk['gsearch'][i] for i in range(len(weeks))]
    chDn['gmbgoogle']=[chDn['gmb'][i]+chDn['gsearch'][i] for i in range(len(weeks))]

    # ── carry spend / verified-leads / STI from the L0 build (platform spend isn't in the warehouse) ──
    # L0 period labels are the week-ENDING Sunday ("3 May"); our RS weeks are Mondays, so the label
    # is Monday+6 days. Computed (not a hardcoded map) so it never goes stale on a window shift.
    def wk_label(w):
        sun = datetime.date.fromisoformat(w) + datetime.timedelta(days=6)
        return f"{sun.day} {sun.strftime('%b')}"
    L0 = json.load(open(os.path.join(ROOT,'data_efficiency.json')))['weekly']; L0A=L0['ALL']; L0P=L0['periods']
    def l0(field):
        out=[None]*len(weeks)
        for w in weeks:
            p=wk_label(w)
            if p in L0P: out[idx[w]]=L0A.get(field,[None]*len(L0P))[L0P.index(p)]
        return out

    # ── REVENUE BLOCK — DB-native from allo_billing.invoices (status='paid' = realized revenue) ──
    # 1st TP Rev (L0 row 33) = SUM(invoice.amount)/1e7 over COMPLETED screening calls in the week,
    # split by clinic location (offline) vs online. amount is in paise → /1e7 = ₹ lakhs.
    # Validated vs L0: tpRev 29/29/31/31/31/29/29 ≈ L0 29.3/29.4/31.7/31.1/30.9/29.1/29.0 (within rounding).
    # The 'paid' (not 'created') filter is the key — 'created' invoices are unpaid/pending.
    revrows = rs("""WITH loc_dedup AS (
        SELECT id, MAX(city) city FROM allo_health.locations WHERE deleted_at IS NULL AND is_active=1 GROUP BY id),
      ap AS (
        SELECT a.id, TO_CHAR(DATE_TRUNC('week',a.start_time),'YYYY-MM-DD') wk,
          CASE WHEN loc.city IS NOT NULL AND loc.city<>'' AND loc.city<>'Practo Online' THEN 1 ELSE 0 END off_flag
        FROM allo_consultations.appointments a
        JOIN allo_consultations.types typ ON typ.id=a.type_id AND typ.name='Screening Call'
        LEFT JOIN loc_dedup loc ON loc.id=a.location_id
        WHERE a.start_time>='2026-03-16' AND a.start_time<'2026-06-22'
          AND a.deleted_at IS NULL AND a.status='COMPLETED'),
      inv AS (
        SELECT e.appointment_id ap_id, i.amount amt
        FROM allo_encounters.encounters e
        JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.deleted_at IS NULL AND i.status='paid'
        WHERE e.deleted_at IS NULL)
      SELECT ap.wk,
        SUM(CASE WHEN ap.off_flag=0 THEN COALESCE(inv.amt,0) ELSE 0 END) tprev_on_paise,
        SUM(CASE WHEN ap.off_flag=1 THEN COALESCE(inv.amt,0) ELSE 0 END) tprev_off_paise,
        COUNT(CASE WHEN ap.off_flag=0 THEN inv.ap_id END) tp_on,
        COUNT(CASE WHEN ap.off_flag=1 THEN inv.ap_id END) tp_off
      FROM ap LEFT JOIN inv ON inv.ap_id=ap.id GROUP BY 1;""")
    tpRevOn=[0.0]*len(weeks); tpRevOff=[0.0]*len(weeks); tpOn=[0]*len(weeks); tpOff=[0]*len(weeks)
    for wk,ron,roff,ton,toff in revrows:
        if wk in idx:
            i=idx[wk]
            tpRevOn[i]=round(int(ron or 0)/1e7,2); tpRevOff[i]=round(int(roff or 0)/1e7,2)
            tpOn[i]=int(ton or 0); tpOff[i]=int(toff or 0)
    tpRev=[round(tpRevOn[i]+tpRevOff[i],2) for i in range(len(weeks))]
    tp=[tpOn[i]+tpOff[i] for i in range(len(weeks))]
    # done & bookings online/offline split from data.json offline scope (all-scope = matches L0)
    OFF = dj.get('offline',{}).get('weekly_funnel',{})
    dnOff=[ (OFF.get(w,{}) or {}).get('calls_done',0) for w in weeks ]
    dnOn=[ max(doneT[i]-dnOff[i],0) for i in range(len(weeks)) ]
    bkOff=[ (OFF.get(w,{}) or {}).get('gross',0) for w in weeks ]
    bkOn=[ max(bookingsT[i]-bkOff[i],0) for i in range(len(weeks)) ]
    # Consult Rev (L0 row 34, pure formula): online done × ₹199 + offline done × ₹499, in ₹ lakhs
    consultRev=[round((dnOn[i]*199+dnOff[i]*499)/1e5,2) for i in range(len(weeks))]
    newRev=[round(tpRev[i]+consultRev[i],2) for i in range(len(weeks))]   # row 35
    # ── SPEND: Google is NATIVE (Google Ads API total × 1.18 GST — verified to match the L0 sheet to the
    #    rupee, and it covers weeks the sheet doesn't). Meta + Practo still come from the sheet (no warehouse
    #    source; Meta needs a token we don't have, Practo has no API). align() carries the sheet series. ──
    def align(a):
        o=[None]*len(weeks)
        for w in weeks:
            p=wk_label(w)
            if p in L0P and p in [wk_label(x) for x in weeks]: o[idx[w]]=a[L0P.index(p)] if L0P.index(p)<len(a) else None
        return o
    L0D = L0['DIRECT']
    _gmap = (lambda g: dict(zip(g['weeks'], g['net'])))(json.load(open(os.path.join(ROOT,'data_ga_total_spend.json'))))
    google   = [round(_gmap[w]*1.18) if w in _gmap else None for w in weeks]      # GST-inclusive, full history
    meta_sp  = align(L0D.get('meta',{}).get('spend',[]))                          # sheet (SyncWith→Meta)
    practo_sp= align(L0D.get('practo',{}).get('spend',[]))                        # sheet (manual)
    # NETWORK spend only where ALL three channels are present — else None ("—") rather than a misleading
    # Google-only total. The Google CHANNEL card still gets full native history via DIRECT below.
    spend    = [ (google[i]+meta_sp[i]+practo_sp[i]) if (google[i] is not None and meta_sp[i] is not None and practo_sp[i] is not None) else None for i in range(len(weeks)) ]
    sti=l0('sti'); vpct=l0('vpct')
    _vl=l0('vleads'); vleads=[_vl[i] if _vl[i] is not None else leadsT[i] for i in range(len(weeks))]  # element-wise fallback to total leads ([None]*n is truthy, so `or leadsT` never fired)
    roas=[round(newRev[i]*1e5/spend[i]*100,1) if spend[i] else None for i in range(len(weeks))]  # row 36 (% form, matches L0)
    aov=[round(tpRev[i]*1e5/tp[i]) if tp[i] else None for i in range(len(weeks))]
    rpc=[round(tpRev[i]*1e5/doneT[i]) if doneT[i] else None for i in range(len(weeks))]     # row 37

    def rate(n,d): return [round(n[i]/d[i]*100) if d[i] else None for i in range(len(weeks))]
    ALL = {'spend':spend,'leads':leadsT,'vleads':vleads,'vpct':vpct,'cpl':[round(spend[i]/vleads[i]) if spend[i] and vleads[i] else None for i in range(len(weeks))],
           'bookings':bookingsT,'b2l':rate(bookT,leadsT),'cpb':[round(spend[i]/bookingsT[i]) if spend[i] and bookingsT[i] else None for i in range(len(weeks))],
           'done':doneT,'b2d':rate(doneT,bookingsT),'cpd':[round(spend[i]/doneT[i]) if spend[i] and doneT[i] else None for i in range(len(weeks))],
           'tp':tp,'done2tp':rate(tp,doneT),'newRev':newRev,'tpRev':tpRev,'consultRev':consultRev,'roas':roas,'aov':aov,'rpc':rpc,'sti':sti,
           'bkOn':bkOn,'bkOff':bkOff,'dnOn':dnOn,'dnOff':dnOff,'b2dOn':rate(dnOn,bkOn),'b2dOff':rate(dnOff,bkOff),
           'tpOn':tpOn,'tpOff':tpOff,'convOn':rate(tpOn,dnOn),'convOff':rate(tpOff,dnOff),
           'tpRevOn':tpRevOn,'tpRevOff':tpRevOff}
    # CONTR (% of network) per channel
    def pctOf(d,T): return [round(d[i]/T[i]*100) if T[i] else 0 for i in range(len(weeks))]
    CONTR={}
    for k in ['gmbgoogle','gsearch','gmb','organic','meta','practo']:
        CONTR[k]={'lead':pctOf(lead.get(k,[0]*len(weeks)),leadsT),'book':pctOf(chBk.get(k,[0]*len(weeks)),bookingsT),
                  'done':pctOf(chDn.get(k,[0]*len(weeks)),doneT),'spend':[0]*len(weeks)}
    plabels=[wk_label(w) for w in weeks]
    # per-channel spend: Google is NATIVE (full history); Meta/Practo carried from the sheet (L0D/align above).
    DIRECT={ch:{m:align(v) for m,v in d.items()} for ch,d in L0D.items()}
    for gk in ('gsearch','gmbgoogle'):                         # override Google spend with the native series
        DIRECT.setdefault(gk,{})['spend']=list(google)
    DIRECT.setdefault('gmb',{})['spend']=[0]*len(weeks)        # GMB Maps = organic, no paid spend
    # Practo is excluded from the Redshift leads table (external feed) → its lead count is 0, which made
    # Book/Lead = bookings÷0 = Infinity. Recover Practo leads from the sheet: leads = spend ÷ CPL.
    _pcpl=DIRECT.get('practo',{}).get('cpl') or []; _psp=DIRECT.get('practo',{}).get('spend') or []
    DIRECT.setdefault('practo',{})['leads']=[ round(_psp[i]/_pcpl[i]) if (i<len(_psp) and i<len(_pcpl) and _psp[i] and _pcpl[i]) else None for i in range(len(weeks)) ]
    # spend SHARE per channel = channel spend ÷ network spend (×100). From DIRECT (external-platform spend)
    # so the scorecard's "Spend %" column works on the Redshift build too, and Meta/Practo split out.
    for k in CONTR:
        dsp=DIRECT.get(k,{}).get('spend')
        CONTR[k]['spend']=[ (round(dsp[i]/spend[i]*100) if (dsp and i<len(dsp) and dsp[i] and spend[i]) else 0) for i in range(len(weeks)) ]
    # ── TIER SPLIT (T1/T2): tier SHARES from per-clinic data (data_clinic_funnel) applied to the network ALL,
    #    so tiers reconcile to network. Google spend measured by city→tier; Meta+Practo allocated by booking share. ──
    T1C={'Bangalore','Mumbai','Pune','Hyderabad','Chennai'}
    T2C={'Navi Mumbai','Coimbatore','Nagpur','Ranchi','Jaipur','Ahmedabad','Surat','Nashik','Aurangabad','Hubli',
         'Mysuru','Mangaluru','Bhopal','Visakhapatnam','Thane','Gandhinagar','Vijayawada'}
    TIERS={}
    try:
        CF=json.load(open(os.path.join(ROOT,'data_clinic_funnel.json'))); cfi={w:i for i,w in enumerate(CF['_meta']['weeks'])}
        def _share(path,cities,DATA,idxmap,arrf):
            out=[]
            for w in weeks:
                j=idxmap.get(w)
                if j is None: out.append(None); continue
                num=den=0.0
                for k,c in DATA.items():
                    if k=='_meta': continue
                    a=arrf(c,path); v=(a[j] if a and j<len(a) else 0) or 0; den+=v
                    if k.split('|')[0] in cities: num+=v
                out.append(num/den if den else 0.0)
            return out
        def _cfarr(c,path):
            a=c
            for p in path.split('.'): a=a.get(p) if isinstance(a,dict) else None
            return a
        GAP=json.load(open(os.path.join(ROOT,'data_ga_city_paid.json'))); gpi={w:i for i,w in enumerate(GAP['_meta']['weeks'])}
        def _garr(c,path): return c.get('spend')
        def onfrac(on,tot): return [ (on[i]/tot[i] if tot[i] else 0) for i in range(len(weeks)) ]
        of_bk=onfrac(bkOn,bookingsT); of_dn=onfrac(dnOn,doneT); of_tp=onfrac(tpOn,tp)
        def tier_block(cities):
            bs=_share('booking.bookings',cities,CF['clinics'],cfi,_cfarr); ds=_share('done.done',cities,CF['clinics'],cfi,_cfarr)
            rs=_share('revenue.rev',cities,CF['clinics'],cfi,_cfarr);     ls=_share('lead.leads_total',cities,CF['clinics'],cfi,_cfarr)
            M=lambda arr,sh,nd=0:[ (round(arr[i]*sh[i],nd) if nd else round(arr[i]*sh[i])) if (arr[i] is not None and sh[i] is not None) else None for i in range(len(weeks)) ]
            t_l=M(leadsT,ls); t_vl=M(vleads,ls); t_b=M(bookingsT,bs); t_d=M(doneT,ds); t_tp=M(tp,ds)
            t_nr=M(newRev,rs,2); t_tpr=M(tpRev,rs,2); t_cr=M(consultRev,rs,2)
            t_sp=[None]*len(weeks)   # spend NOT split by tier — Meta/Practo aren't city-targeted and we don't allocate (per request)
            t_bkOn=[round(t_b[i]*of_bk[i]) if t_b[i] is not None else None for i in range(len(weeks))]; t_bkOff=[t_b[i]-t_bkOn[i] if t_b[i] is not None else None for i in range(len(weeks))]
            t_dnOn=[round(t_d[i]*of_dn[i]) if t_d[i] is not None else None for i in range(len(weeks))]; t_dnOff=[t_d[i]-t_dnOn[i] if t_d[i] is not None else None for i in range(len(weeks))]
            t_tpOn=[round(t_tp[i]*of_tp[i]) if t_tp[i] is not None else None for i in range(len(weeks))]; t_tpOff=[t_tp[i]-t_tpOn[i] if t_tp[i] is not None else None for i in range(len(weeks))]
            R=lambda n,dd:[round(n[i]/dd[i]*100) if (n[i] is not None and dd[i]) else None for i in range(len(weeks))]
            D=lambda n,dd,k=1:[round(n[i]/dd[i]*k) if (n[i] is not None and dd[i]) else None for i in range(len(weeks))]
            return {'leads':t_l,'vleads':t_vl,'vpct':vpct,'bookings':t_b,'done':t_d,'tp':t_tp,
                    'newRev':t_nr,'tpRev':t_tpr,'consultRev':t_cr,'spend':t_sp,'sti':sti,
                    'cpl':[round(t_sp[i]/t_vl[i]) if (t_sp[i] and t_vl[i]) else None for i in range(len(weeks))],
                    'cpb':[round(t_sp[i]/t_b[i]) if (t_sp[i] and t_b[i]) else None for i in range(len(weeks))],
                    'cpd':[round(t_sp[i]/t_d[i]) if (t_sp[i] and t_d[i]) else None for i in range(len(weeks))],
                    'roas':[round(t_nr[i]*1e5/t_sp[i]*100,1) if (t_nr[i] is not None and t_sp[i]) else None for i in range(len(weeks))],
                    'aov':D(t_tpr,t_tp,100000),'rpc':D(t_tpr,t_d,100000),
                    'b2l':R(t_b,t_l),'b2d':R(t_d,t_b),'done2tp':R(t_tp,t_d),
                    'bkOn':t_bkOn,'bkOff':t_bkOff,'dnOn':t_dnOn,'dnOff':t_dnOff,'tpOn':t_tpOn,'tpOff':t_tpOff,
                    'b2dOn':R(t_dnOn,t_bkOn),'b2dOff':R(t_dnOff,t_bkOff),'convOn':R(t_tpOn,t_dnOn),'convOff':R(t_tpOff,t_dnOff)}
        TIERS={'T1':tier_block(T1C),'T2':tier_block(T2C)}
    except Exception as e:
        sys.stderr.write('tier split skipped: '+repr(e)+'\n')
    out={'_meta':{'source':'Redshift-native funnel + revenue. Leads/booked: main_source_wise_leads. Bookings/done: data.json gross. Revenue (1st TP Rev): allo_billing.invoices status=paid over COMPLETED screening calls, split offline/online; Consult Rev = done_on×199+done_off×499; New Rev = TP+Consult; RoAS/AOV/RPC derived. Spend: Google=NATIVE Google Ads API (total cost ×1.18 GST — matches L0 sheet exactly, full history); Meta=SyncWith/FB sheet, Practo=Practo sheet (no warehouse/API source). Network spend/CPL/CPB/RoAS are null for weeks before the sheet window (Meta/Practo missing) to avoid Google-only distortion; the Google channel card has full history. Verified-lead% carried from L0. TIERS (T1/T2): volume+revenue split by per-clinic share; spend/CPL/CPB/CPD/RoAS NOT split by tier (Meta/Practo not city-targeted, no allocation).','weekly':plabels},
         'weekly':{'periods':plabels,'ALL':ALL,'CONTR':CONTR,'DIRECT':DIRECT,'TIERS':TIERS},
         'monthly':json.load(open(os.path.join(ROOT,'data_efficiency.json')))['monthly']}
    json.dump(out, open(os.path.join(ROOT,'data_efficiency_rs.json'),'w'), separators=(',',':'))

    # ── comparison print RS vs L0 ──
    print('=== RS vs L0 (sheet) — network leads / bookings / done ===')
    print('%-8s | %-15s | %-15s | %-15s'%('week','LEADS rs/L0','BOOKINGS rs/L0','DONE rs/L0'))
    for w in weeks:
        i=idx[w]; p=wk_label(w)
        l0l=L0A['leads'][L0P.index(p)] if p in L0P else None
        l0b=L0A['bookings'][L0P.index(p)] if p in L0P else None
        l0d=L0A['done'][L0P.index(p)] if p in L0P else None
        flag=' <-- LEADS MISMATCH' if (l0l and abs(leadsT[i]-l0l)>l0l*0.1) else ''
        print('%-8s | %5d / %-7s | %5d / %-7s | %5d / %s%s'%(p or w, leadsT[i], int(l0l) if l0l else '—', bookingsT[i], int(l0b) if l0b else '—', doneT[i], int(l0d) if l0d else '—', flag))
    print('\n=== RS vs L0 — revenue (₹ lakhs) ===')
    print('%-8s | %-13s | %-13s | %-13s'%('week','tpRev rs/L0','consult rs/L0','newRev rs/L0'))
    for w in weeks:
        i=idx[w]; p=wk_label(w)
        def g(f): return L0A[f][L0P.index(p)] if p in L0P and f in L0A else None
        print('%-8s | %5.1f / %-5s | %5.2f / %-5s | %5.1f / %s'%(p or w, tpRev[i], g('tpRev'), consultRev[i], g('consultRev'), newRev[i], g('newRev')))

if __name__=='__main__': main()
