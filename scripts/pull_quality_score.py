#!/usr/bin/env python3
"""Pull Quality Score + AR/LP per campaign per week → data_quality_score.json
   { "<stem>": { "<week label>": { "qs": float, "ar": int%, "lp": int% } } }
QS = cost-weighted average across enabled keywords (Σ QS·cost ÷ Σ cost).
AR% = % of impressions where ad relevance was BELOW_AVERAGE (impression-weighted).
LP% = % of impressions where landing page experience was BELOW_AVERAGE (impression-weighted).
build_campaign_compose.py merges these onto acq rows.
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
    ('Jul 6-12','2026-07-06','2026-07-12'),('Jul 13-19','2026-07-13','2026-07-19'),
    ('Jul 20-26','2026-07-20','2026-07-26')]
def fn_of(name): return re.sub(r'[^a-z0-9]+','_',name.lower()).strip('_')
out={}
for label,s,e in WK:
    # stem -> [Σ qs*cost, Σ cost, imp_ar_bad, imp_lp_bad, imp_total]
    acc={}
    q=(f"SELECT campaign.name, metrics.cost_micros, metrics.impressions, "
       f"ad_group_criterion.quality_info.quality_score, "
       f"ad_group_criterion.quality_info.creative_quality_score, "
       f"ad_group_criterion.quality_info.post_click_quality_score "
       f"FROM keyword_view WHERE segments.date BETWEEN '{s}' AND '{e}' AND metrics.impressions>0")
    n=0
    for r in ga.search(customer_id=CID, query=q):
        qi=r.ad_group_criterion.quality_info
        qs=qi.quality_score
        if not qs: continue   # keyword has no QS (skip; don't dilute with 0)
        cost=r.metrics.cost_micros/1e6
        imp=r.metrics.impressions
        w=cost if cost>0 else 0.0001   # tiny floor so a 0-cost keyword still counts a hair
        ar_bad=1 if int(qi.creative_quality_score)==2 else 0   # 2=BELOW_AVERAGE in QualityScoreBucket enum
        lp_bad=1 if int(qi.post_click_quality_score)==2 else 0
        stem=fn_of(r.campaign.name); a=acc.setdefault(stem,[0.0,0.0,0,0,0])
        a[0]+=qs*w; a[1]+=w; a[2]+=ar_bad*imp; a[3]+=lp_bad*imp; a[4]+=imp; n+=1
    for stem,a in acc.items():
        qs_val=round(a[0]/a[1],2) if a[1]>0 else None
        ar_val=round(a[2]/a[4]*100) if a[4]>0 else None
        lp_val=round(a[3]/a[4]*100) if a[4]>0 else None
        out.setdefault(stem,{})[label]={'qs':qs_val,'ar':ar_val,'lp':lp_val}
    print(f"{label}: {len(acc)} campaigns with QS ({n} keywords)")
json.dump(out, open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'data_quality_score.json'),'w'), separators=(',',':'))
print(f"wrote data_quality_score.json · {len(out)} campaign stems")
