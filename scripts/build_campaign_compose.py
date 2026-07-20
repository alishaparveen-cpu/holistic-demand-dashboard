#!/usr/bin/env python3
"""Build data_campaign_compose.json — the all-city Google-Ads "Campaign Compose" cube.

Two independently-composable halves per city (mirrors the Excel we validated):
  ACQUISITION (by category × match-type × week) — from the google-ads-audit funnel reports:
     budget(₹/day) · bid(CPC ceiling) · spend(Cost) · impr · elig(=impr/IS) · locimpr · click · locclick
  FUNNEL (by channel × medium × category × week) — from data_leads_city (same 3-tier waterfall cat):
     leads · booked · done · spend(attributed Google $ by lead; GMB=0) · rev(=done × per-cat RPC)
Reports exist for ~25 cities; the funnel covers all cube cities. Cities w/o reports → funnel-only.
Run: python3 scripts/build_campaign_compose.py   (no Redshift — reads the reports + the leads cube)
"""
import os, re, json, glob
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.expanduser('~/Downloads/claude-skills/marketing/google-ads/reports/funnel')
WK = {'w1':'Jun 8-14','w2':'Jun 15-21','w3':'Jun 22-28','w4':'Jun 29-Jul 5','w5':'Jul 6-12','w6':'Jul 13-19'}
WKS = [WK[f'w{i}'] for i in range(1,7)]
WKIDX = {WK['w1']:5, WK['w2']:4, WK['w3']:3, WK['w4']:2, WK['w5']:1, WK['w6']:0}   # cube weeks newest-first (idx0=Jul13)
# report city token -> cube city name (aliases where they differ)
CITYFIX = {'hubballi':'Hubli','vizag':'Visakhapatnam','mangalore':'Mangaluru','navi_mumbai':'Navi Mumbai'}
def city_of(tok): return CITYFIX.get(tok) or tok.replace('_',' ').title()
MT = {'exact_local':'Exact-Local','exact':'Exact','phrase_local':'Phrase-Local'}
CAT = {'sh':'SH','std':'STI','mh':'MH'}
CHMAP = {'GMB':'GMB','Google Ads':'Google'}

def num(s):
    m = re.search(r'-?[\d,]+(?:\.\d+)?', s or '')
    return float(m.group().replace(',','')) if m else None

def parse_report(path):
    """→ dict of the acquisition fields we need (2nd table column = the campaign value)."""
    val = {}
    for ln in open(path):
        if not ln.startswith('|'): continue
        c = [x.strip() for x in ln.strip().strip('|').split('|')]
        if len(c) < 2: continue
        key = c[0].replace('*','').replace('·','').strip().lower(); v = c[1]
        val[key] = v
    def g(k): return num(val.get(k))
    is_pct = g('is')
    impr = g('impression')
    return dict(budget=g('budget'), bid=g('bid'), spend=g('cost'), impr=impr,
                elig=(impr/(is_pct/100) if impr and is_pct else (impr or 0)),
                locimpr=g('location impressions'), click=g('click'), locclick=g('loc clicks'),
                rev=g('revenue'), done=g('done'))

def main():
    # ---- ACQUISITION: parse every campaign report ----
    acq = {}   # city -> [{cat,mt,wk, budget,bid,spend,impr,elig,locimpr,click,locclick,rev,done}]
    pat = re.compile(r'^(t[12])_(.+?)_(sh|std|mh)_(exact_local|phrase_local|exact)_(w[1-6])\.md$')
    for fn in os.listdir(REPORTS):
        m = pat.match(fn)
        if not m: continue
        _, ctok, cat, mt, wk = m.groups()
        if wk not in WK: continue
        city = city_of(ctok); r = parse_report(os.path.join(REPORTS, fn))
        acq.setdefault(city, []).append(dict(cat=CAT[cat], mt=MT[mt], wk=WK[wk], **r))
    # ---- per-city × category RPC (campaign rev ÷ done) ----
    rpc = {}
    for city, rows in acq.items():
        cd = {}
        for r in rows:
            cd.setdefault(r['cat'], [0,0]); cd[r['cat']][0]+=r.get('rev') or 0; cd[r['cat']][1]+=r.get('done') or 0
        tot = [sum(cd[c][0] for c in cd), sum(cd[c][1] for c in cd)]
        rpc[city] = {c:(round(cd[c][0]/cd[c][1],1) if cd[c][1] else None) for c in cd}
        rpc[city]['_blended'] = round(tot[0]/tot[1],1) if tot[1] else 3200.0
    def rpc_of(city,cat):
        d = rpc.get(city,{}); return d.get(cat) or d.get('_blended',3200.0)
    # ---- FUNNEL: from the leads cube (3-tier waterfall cat already in the cube) ----
    cube = json.load(open(os.path.join(ROOT,'data_leads_city.json')))
    def MED(m): return 'Call' if m=='call' else 'Web' if m=='web' else 'WhatsApp' if m in('whatsapp','wa_gmb','wa_org','wa_outbound') else 'Other'
    def FCAT(x): return x if x in('SH','STI','MH','Other') else 'Uncategorized'
    from collections import defaultdict
    fun = defaultdict(lambda:[0,0,0,0,0])   # (city,ch,med,cat,wk) -> leads,booked,done,booked_offline,booked_online
    for city, node in cube.items():
        if city=='_meta': continue
        for cel in node.get('cells',[]):
            ch = CHMAP.get(cel.get('ch'))
            if not ch: continue
            med=MED(cel.get('md')); cat=FCAT(cel.get('cat'))
            booked=cel.get('bk')!='notbooked'; done=cel.get('dq')=='done'; seg=cel.get('bkseg'); w=cel.get('w',[])
            for wk,idx in WKIDX.items():
                lv = w[idx] if idx < len(w) else 0
                if lv==0: continue
                k=(city,ch,med,cat,wk); fun[k][0]+=lv
                if booked:
                    fun[k][1]+=lv
                    if seg=='offline': fun[k][3]+=lv
                    elif seg=='online': fun[k][4]+=lv
                if done: fun[k][2]+=lv
    # attribute Google spend across Google-channel leads (proportional); GMB=0
    gsp = defaultdict(float); gld = defaultdict(float)
    for city, rows in acq.items():
        for r in rows: gsp[(city,r['wk'])] += r.get('spend') or 0
    for (city,ch,med,cat,wk),v in fun.items():
        if ch=='Google': gld[(city,wk)] += v[0]
    # ---- assemble the cube ----
    out = {'_meta':{'weeks':WKS, 'cats':['SH','STD','MH'], 'mts':['Exact-Local','Exact','Phrase-Local'],
                    'chans':['GMB','Google'], 'meds':['Call','Web','WhatsApp'],
                    'fcats':['SH','STI','MH','Other','Uncategorized'],
                    'note':'Google-Ads compose: ACQUISITION (cat×matchtype, from funnel reports) + FUNNEL (chan×med×cat, from leads cube, 3-tier waterfall). RPC per-category from reports. spend attributed to Google leads proportionally; GMB=0.'}}
    cities = sorted(set(list(acq.keys()) + [c for c in cube if c!='_meta']))
    for city in cities:
        arows = [{'cat':r['cat'],'mt':r['mt'],'wk':r['wk'],'budget':round(r.get('budget') or 0,1),
                  'bid':r.get('bid'),'sp':round(r.get('spend') or 0,1),'impr':round(r.get('impr') or 0),
                  'elig':round(r.get('elig') or 0),'locimpr':round(r.get('locimpr') or 0),
                  'click':round(r.get('click') or 0),'locclick':round(r.get('locclick') or 0)}
                 for r in acq.get(city,[])]
        frows = []
        for (c2,ch,med,cat,wk),v in fun.items():
            if c2!=city: continue
            L,B,D,BO,BN = v
            spend = round(gsp.get((city,wk),0)*(L/gld[(city,wk)]),1) if ch=='Google' and gld.get((city,wk)) else 0
            frows.append({'ch':ch,'med':med,'cat':cat,'wk':wk,'lead':L,'bk':B,'dn':D,'bko':BO,'bkn':BN,'sp':spend,'rev':round(D*rpc_of(city,cat),1)})
        if arows or frows:
            out[city] = {'acq':arows, 'fun':frows, 'rpc':rpc.get(city,{})}
    json.dump(out, open(os.path.join(ROOT,'data_campaign_compose.json'),'w'), separators=(',',':'))
    nA = sum(1 for c in out if c!='_meta' and out[c]['acq'])
    nF = sum(1 for c in out if c!='_meta' and out[c]['fun'])
    print(f'wrote data_campaign_compose.json · {len([c for c in out if c!="_meta"])} cities ({nA} w/ acquisition, {nF} w/ funnel)')

if __name__ == '__main__':
    main()
