#!/usr/bin/env python3
"""Pull Search Lost Impression Share — rank & budget — per campaign per week (all 6 weeks) from the
Google Ads API → data_lost_is.json  { "<report_stem>": { "<week label>": {"rank":0.x,"budget":0.y} } }.
IS + lost(rank) + lost(budget) ≈ 100%. build_campaign_compose.py merges these into acq rows.
Reads creds from ~/.claude/.mcp.json.
"""
import json, os, re
REP=os.path.expanduser('~/Downloads/claude-skills/marketing/google-ads/reports/funnel')
cfg=json.load(open(os.path.expanduser('~/.claude/.mcp.json')))['mcpServers']['@allo/mcp-google-ads']['env']
from google.ads.googleads.client import GoogleAdsClient
client=GoogleAdsClient.load_from_dict({'developer_token':cfg['GOOGLE_ADS_DEVELOPER_TOKEN'],
    'client_id':cfg['GOOGLE_ADS_CLIENT_ID'],'client_secret':cfg['GOOGLE_ADS_CLIENT_SECRET'],
    'refresh_token':cfg['GOOGLE_ADS_REFRESH_TOKEN'],'login_customer_id':'5098518843','use_proto_plus':True})
ga=client.get_service('GoogleAdsService'); CID='3190189170'
WK=[('Jun 8-14','2026-06-08','2026-06-14'),('Jun 15-21','2026-06-15','2026-06-21'),
    ('Jun 22-28','2026-06-22','2026-06-28'),('Jun 29-Jul 5','2026-06-29','2026-07-05'),
    ('Jul 6-12','2026-07-06','2026-07-12'),('Jul 13-19','2026-07-13','2026-07-19')]
def fn_of(name): return re.sub(r'[^a-z0-9]+','_',name.lower()).strip('_')
out={}
for label,s,e in WK:
    q=(f"SELECT campaign.name, metrics.impressions, metrics.search_impression_share, "
       f"metrics.search_rank_lost_impression_share, metrics.search_budget_lost_impression_share "
       f"FROM campaign WHERE segments.date BETWEEN '{s}' AND '{e}' AND metrics.impressions>0")
    n=0
    for r in ga.search(customer_id=CID, query=q):
        stem=fn_of(r.campaign.name); n+=1
        out.setdefault(stem,{})[label]={
            'rank': round(r.metrics.search_rank_lost_impression_share or 0, 4),
            'budget': round(r.metrics.search_budget_lost_impression_share or 0, 4)}
    print(f"{label}: {n} campaigns")
json.dump(out, open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'data_lost_is.json'),'w'), separators=(',',':'))
print(f"wrote data_lost_is.json · {len(out)} campaign stems")
