#!/usr/bin/env python3
"""Re-pull ALL 6 weeks for every ONLINE Google-Ads campaign (ROI_Online / CC_Online /
ONL_LT / Brand_Allo / PD_Online) directly from the API and rewrite their reports/funnel/*.md.
Fixes empty/partial audit-skill report files (e.g. Brand_Allo_CC & ROI_Online_Brand had blank
w1-w5 files → the Online compose entry showed ₹0 in those weeks even though they've run all along).
Reads creds from ~/.claude/.mcp.json. Online campaigns have ~0 location impressions.
"""
import json, os, re
REP=os.path.expanduser('~/Downloads/claude-skills/marketing/google-ads/reports/funnel')
cfg=json.load(open(os.path.expanduser('~/.claude/.mcp.json')))['mcpServers']['@allo/mcp-google-ads']['env']
from google.ads.googleads.client import GoogleAdsClient
client=GoogleAdsClient.load_from_dict({'developer_token':cfg['GOOGLE_ADS_DEVELOPER_TOKEN'],
    'client_id':cfg['GOOGLE_ADS_CLIENT_ID'],'client_secret':cfg['GOOGLE_ADS_CLIENT_SECRET'],
    'refresh_token':cfg['GOOGLE_ADS_REFRESH_TOKEN'],'login_customer_id':'5098518843','use_proto_plus':True})
ga=client.get_service('GoogleAdsService'); CID='3190189170'
WK=[('w1','2026-06-08','2026-06-14'),('w2','2026-06-15','2026-06-21'),('w3','2026-06-22','2026-06-28'),
    ('w4','2026-06-29','2026-07-05'),('w5','2026-07-06','2026-07-12'),('w6','2026-07-13','2026-07-19')]
WKLBL={'w1':'2026-06-08 → 2026-06-14','w2':'2026-06-15 → 2026-06-21','w3':'2026-06-22 → 2026-06-28',
       'w4':'2026-06-29 → 2026-07-05','w5':'2026-07-06 → 2026-07-12','w6':'2026-07-13 → 2026-07-19'}
ONLINE=re.compile(r'^(roi_online|cc_online|onl_lt|brand_allo|pd_online)_', re.I)
def fn_of(name): return re.sub(r'[^a-z0-9]+','_',name.lower()).strip('_')
LOC={'CALLS','GET_DIRECTIONS','LOCATION_EXPANSION','CALL_TRACKING'}
written=0; grand=0
for wk,s,e in WK:
    perf={}
    q1=(f"SELECT campaign.name, campaign_budget.amount_micros, metrics.cost_micros, metrics.impressions, "
        f"metrics.clicks, metrics.search_impression_share FROM campaign "
        f"WHERE segments.date BETWEEN '{s}' AND '{e}' AND metrics.impressions>0")
    for r in ga.search(customer_id=CID, query=q1):
        nm=r.campaign.name
        if not ONLINE.match(fn_of(nm)): continue
        p=perf.setdefault(nm, dict(budget=0,cost=0,impr=0,click=0,is_num=0))
        p['budget']=r.campaign_budget.amount_micros/1e6
        p['cost']+=r.metrics.cost_micros/1e6; p['impr']+=r.metrics.impressions; p['click']+=r.metrics.clicks
        p['is_num']=(r.metrics.search_impression_share or 0)*100
    q2=(f"SELECT campaign.name, segments.click_type, metrics.clicks FROM campaign "
        f"WHERE segments.date BETWEEN '{s}' AND '{e}' AND metrics.clicks>0")
    loc={}
    for r in ga.search(customer_id=CID, query=q2):
        if r.segments.click_type.name in LOC and ONLINE.match(fn_of(r.campaign.name)):
            loc[r.campaign.name]=loc.get(r.campaign.name,0)+r.metrics.clicks
    for nm,p in perf.items():
        stem=fn_of(nm); locclick=loc.get(nm,0)
        md=(f"# {nm} — {WKLBL[wk]} cohort [{wk} · full week, GAQL pull]\n\n"
            f"| Stage | {nm} | Total |\n|---|---:|---:|\n"
            f"| **Budget** | ₹{p['budget']:,.0f}/d | ₹{p['budget']:,.0f}/d |\n"
            f"| **Bid** | — | — |\n"
            f"| **Cost** | **{p['cost']:,.0f}** | **{p['cost']:,.0f}** |\n"
            f"| impression | {p['impr']:,.0f} | {p['impr']:,.0f} |\n"
            f"|  · IS | {p['is_num']:.1f}% | — |\n"
            f"|  · Location Impressions | 0 | 0 |\n"
            f"| click | {p['click']:,.0f} | {p['click']:,.0f} |\n"
            f"|  · Loc Clicks | {locclick:,.0f} | {locclick:,.0f} |\n")
        open(os.path.join(REP, stem+'_'+wk+'.md'),'w').write(md); written+=1; grand+=p['cost']
    print(f"{wk}: {len(perf)} online campaigns · ₹{sum(p['cost'] for p in perf.values()):,.0f}")
print(f"wrote {written} report files · total online spend across 6 weeks ₹{grand:,.0f}")
