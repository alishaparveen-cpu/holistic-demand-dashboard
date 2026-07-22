#!/usr/bin/env python3
"""Pull Quality Score per campaign per week (all 6 weeks) → data_quality_score.json
   { "<report_stem>": { "<week label>": qs } }.
QS lives on keywords; the campaign value is the COST-WEIGHTED average across its enabled keywords
(a low-QS keyword burning budget pulls the score down more than a low-QS keyword that barely spends).
build_campaign_compose.py merges these onto acq rows; the dashboard cost-weights across selected campaigns.
Reads creds from ~/.claude/.mcp.json.
"""
import json, os, re
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
    acc={}   # stem -> [Σ qs*cost, Σ cost]
    q=(f"SELECT campaign.name, ad_group_criterion.quality_info.quality_score, metrics.cost_micros "
       f"FROM keyword_view WHERE segments.date BETWEEN '{s}' AND '{e}' AND metrics.impressions>0")
    n=0
    for r in ga.search(customer_id=CID, query=q):
        qs=r.ad_group_criterion.quality_info.quality_score
        if not qs: continue   # keyword has no QS (skip; don't dilute with 0)
        cost=r.metrics.cost_micros/1e6
        w=cost if cost>0 else 0.0001   # tiny floor so a 0-cost-but-has-QS keyword still counts a hair
        stem=fn_of(r.campaign.name); a=acc.setdefault(stem,[0.0,0.0])
        a[0]+=qs*w; a[1]+=w; n+=1
    for stem,(num,den) in acc.items():
        if den>0: out.setdefault(stem,{})[label]=round(num/den,2)
    print(f"{label}: {len(acc)} campaigns with QS ({n} keywords)")
json.dump(out, open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'data_quality_score.json'),'w'), separators=(',',':'))
print(f"wrote data_quality_score.json · {len(out)} campaign stems")
