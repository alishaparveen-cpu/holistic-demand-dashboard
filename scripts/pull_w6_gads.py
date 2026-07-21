#!/usr/bin/env python3
"""One-off: pull the FULL completed week 2026-07-13..19 (w6) from Google Ads and
rewrite reports/funnel/*_w6.md (the mid-week partial capture) so the compose cube's
w6 acquisition is a whole week. Reads creds from ~/.claude/.mcp.json (refresh token).
Only the 8 acquisition rows build_campaign_compose parses are written.
Bid + Location-Impression ratio are carried over from each campaign's w5 report (settings).
"""
import json, os, re, glob
START,END='2026-07-13','2026-07-19'
REP=os.path.expanduser('~/Downloads/claude-skills/marketing/google-ads/reports/funnel')
cfg=json.load(open(os.path.expanduser('~/.claude/.mcp.json')))['mcpServers']['@allo/mcp-google-ads']['env']
from google.ads.googleads.client import GoogleAdsClient
client=GoogleAdsClient.load_from_dict({'developer_token':cfg['GOOGLE_ADS_DEVELOPER_TOKEN'],
    'client_id':cfg['GOOGLE_ADS_CLIENT_ID'],'client_secret':cfg['GOOGLE_ADS_CLIENT_SECRET'],
    'refresh_token':cfg['GOOGLE_ADS_REFRESH_TOKEN'],'login_customer_id':'5098518843','use_proto_plus':True})
ga=client.get_service('GoogleAdsService'); CID='3190189170'
def fn_of(name): return re.sub(r'[^a-z0-9]+','_',name.lower()).strip('_')   # campaign name → report file stem
LOC={'CALLS','GET_DIRECTIONS','LOCATION_EXPANSION','CALL_TRACKING'}
# 1) campaign performance
perf={}
q1=(f"SELECT campaign.name, campaign_budget.amount_micros, metrics.cost_micros, metrics.impressions, "
    f"metrics.clicks, metrics.search_impression_share FROM campaign "
    f"WHERE segments.date BETWEEN '{START}' AND '{END}' AND metrics.impressions>0")
n=0
for r in ga.search(customer_id=CID, query=q1):
    n+=1; nm=r.campaign.name
    p=perf.setdefault(nm, dict(budget=0,cost=0,impr=0,click=0,is_num=0))
    p['budget']=r.campaign_budget.amount_micros/1e6
    p['cost']+=r.metrics.cost_micros/1e6; p['impr']+=r.metrics.impressions; p['click']+=r.metrics.clicks
    p['is_num']=(r.metrics.search_impression_share or 0)*100
print(f"pulled {n} campaign rows · {len(perf)} campaigns with impressions")
# 2) location clicks via click_type
q2=(f"SELECT campaign.name, segments.click_type, metrics.clicks FROM campaign "
    f"WHERE segments.date BETWEEN '{START}' AND '{END}' AND metrics.clicks>0")
loc={}
for r in ga.search(customer_id=CID, query=q2):
    if r.segments.click_type.name in LOC: loc[r.campaign.name]=loc.get(r.campaign.name,0)+r.metrics.clicks
# carry bid + loc-impr ratio from each campaign's w5 report
def w5_bid_and_locratio(stem):
    p=os.path.join(REP, stem+'_w5.md'); bid=None; ratio=0
    if os.path.exists(p):
        imp=li=None
        for ln in open(p):
            if not ln.startswith('|'): continue
            c=[x.strip() for x in ln.strip().strip('|').split('|')]
            k=c[0].replace('*','').replace('·','').strip().lower() if c else ''
            m=re.search(r'\d[\d,]*(?:\.\d+)?', c[1]) if len(c)>1 else None
            v=float(m.group().replace(',','')) if m else None
            if k=='bid': bid=v
            if k=='impression': imp=v
            if k=='location impressions': li=v
        if imp and li is not None: ratio=li/imp
    return bid, ratio
written=0
for nm,p in perf.items():
    stem=fn_of(nm)
    bid,ratio=w5_bid_and_locratio(stem)
    locimpr=round(p['impr']*ratio)
    locclick=loc.get(nm,0)
    md=(f"# {nm} — 2026-07-13 → 2026-07-19 cohort [w6 · full week, GAQL pull]\n\n"
        f"| Stage | {nm} | Total |\n|---|---:|---:|\n"
        f"| **Budget** | ₹{p['budget']:,.0f}/d | ₹{p['budget']:,.0f}/d |\n"
        f"| **Bid** | {('₹%.0f ceiling'%bid) if bid else '—'} | — |\n"
        f"| **Cost** | **{p['cost']:,.0f}** | **{p['cost']:,.0f}** |\n"
        f"| impression | {p['impr']:,.0f} | {p['impr']:,.0f} |\n"
        f"|  · IS | {p['is_num']:.1f}% | — |\n"
        f"|  · Location Impressions | {locimpr:,.0f} | {locimpr:,.0f} |\n"
        f"| click | {p['click']:,.0f} | {p['click']:,.0f} |\n"
        f"|  · Loc Clicks | {locclick:,.0f} | {locclick:,.0f} |\n")
    open(os.path.join(REP, stem+'_w6.md'),'w').write(md); written+=1
print(f"wrote {written} *_w6.md full-week reports")
# quick totals for a sanity check
tot=sum(p['cost'] for p in perf.values())
print(f"total w6 spend across all campaigns: ₹{tot:,.0f}")
