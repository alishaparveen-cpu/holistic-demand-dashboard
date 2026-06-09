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
import os, sys, subprocess, json
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
      FROM production.public.main_source_wise_leads WHERE week>='2026-03-16' GROUP BY 1,2;""")
    weeks = sorted({r[0] for r in rows})                       # oldest-first
    weeks = [w for w in weeks if w<='2026-06-01']              # drop the current partial week
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

    # ── week→L0-label map; spend / verified-lead% / STI stay external (platform spend, not in warehouse) ──
    lab = {'2026-06-01':'7 Jun','2026-05-25':'31 May','2026-05-18':'24 May','2026-05-11':'17 May','2026-05-04':'10 May','2026-04-27':'3 May','2026-04-20':'26 Apr','2026-04-13':'19 Apr'}
    L0 = json.load(open(os.path.join(ROOT,'data_efficiency.json')))['weekly']; L0A=L0['ALL']; L0P=L0['periods']
    def l0(field):
        out=[None]*len(weeks)
        for w in weeks:
            p=lab.get(w);
            if p and p in L0P: out[idx[w]]=L0A.get(field,[None]*len(L0P))[L0P.index(p)]
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
        WHERE a.start_time>='2026-03-09' AND a.start_time<'2026-06-08'
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
    spend=l0('spend'); vleads=l0('vleads') or leadsT; sti=l0('sti'); vpct=l0('vpct')
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
    # Google spend share from data_marketing (approx); Meta/Practo flagged 0 (need source)
    plabels=[lab.get(w,w) for w in weeks]
    # per-channel spend/cost (Google from Redshift-via-sheet, Meta from SyncWith/FB sheet, Practo from Practo sheet)
    # carried from the L0 build aligned to RS weeks — these are external-platform spends, not in the warehouse.
    L0D=json.load(open(os.path.join(ROOT,'data_efficiency.json')))['weekly']['DIRECT']
    def align(a):
        o=[None]*len(weeks)
        for w in weeks:
            p=lab.get(w)
            if p and p in L0P and p in [lab.get(x) for x in weeks]: o[idx[w]]=a[L0P.index(p)] if L0P.index(p)<len(a) else None
        return o
    DIRECT={ch:{m:align(v) for m,v in d.items()} for ch,d in L0D.items()}
    out={'_meta':{'source':'Redshift-native funnel + revenue. Leads/booked: main_source_wise_leads. Bookings/done: data.json gross. Revenue (1st TP Rev): allo_billing.invoices status=paid over COMPLETED screening calls, split offline/online; Consult Rev = done_on×199+done_off×499; New Rev = TP+Consult; RoAS/AOV/RPC derived. Spend: Google=Redshift, Meta=SyncWith/FB sheet, Practo=Practo sheet (external platforms, carried from L0). Verified-lead% carried from L0.','weekly':plabels},
         'weekly':{'periods':plabels,'ALL':ALL,'CONTR':CONTR,'DIRECT':DIRECT},
         'monthly':json.load(open(os.path.join(ROOT,'data_efficiency.json')))['monthly']}
    json.dump(out, open(os.path.join(ROOT,'data_efficiency_rs.json'),'w'), separators=(',',':'))

    # ── comparison print RS vs L0 ──
    print('=== RS vs L0 (sheet) — network leads / bookings / done ===')
    print('%-8s | %-15s | %-15s | %-15s'%('week','LEADS rs/L0','BOOKINGS rs/L0','DONE rs/L0'))
    for w in weeks:
        i=idx[w]; p=lab.get(w)
        l0l=L0A['leads'][L0P.index(p)] if p in L0P else None
        l0b=L0A['bookings'][L0P.index(p)] if p in L0P else None
        l0d=L0A['done'][L0P.index(p)] if p in L0P else None
        flag=' <-- LEADS MISMATCH' if (l0l and abs(leadsT[i]-l0l)>l0l*0.1) else ''
        print('%-8s | %5d / %-7s | %5d / %-7s | %5d / %s%s'%(p or w, leadsT[i], int(l0l) if l0l else '—', bookingsT[i], int(l0b) if l0b else '—', doneT[i], int(l0d) if l0d else '—', flag))
    print('\n=== RS vs L0 — revenue (₹ lakhs) ===')
    print('%-8s | %-13s | %-13s | %-13s'%('week','tpRev rs/L0','consult rs/L0','newRev rs/L0'))
    for w in weeks:
        i=idx[w]; p=lab.get(w)
        def g(f): return L0A[f][L0P.index(p)] if p in L0P and f in L0A else None
        print('%-8s | %5.1f / %-5s | %5.2f / %-5s | %5.1f / %s'%(p or w, tpRev[i], g('tpRev'), consultRev[i], g('consultRev'), newRev[i], g('newRev')))

if __name__=='__main__': main()
