#!/usr/bin/env python3
"""LIVE Google Ads pull → data_ga_city.json (city-level SH Exact Local health for the diagnostic).

Standalone: stdlib only (urllib + json). No skill package, no pip deps. Talks to the Google Ads
REST API directly, so it runs anywhere the 4 OAuth credentials are present.

Credentials (same 4 the Google Ads MCP server uses) — set as env vars:
  GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET, GOOGLE_ADS_DEVELOPER_TOKEN, GOOGLE_ADS_REFRESH_TOKEN
Account 3190189170, login (MCC) 5098518843.

What it pulls, per T1_/T2_<City>_SH_Exact_Local campaign:
  • Weekly (W0 latest, W1 prior): search impression share, rank-lost IS, budget-lost IS,
    avg CPC, cost, budget utilisation        ← metrics.* on `campaign`, segmented by week
  • Current snapshot: Quality Score, Ad-relevance drag, LP-experience drag
                                              ← keyword quality components on `keyword_view`
QS/drag have no week history in the API, so their *_prev come from the previous run's JSON
(current → prev shift). The marketing "suggestion" is derived from the drags/rank/budget.

Run:  GOOGLE_ADS_*=... python3 scripts/pull_ga_city.py   # writes data_ga_city.json next to the others
"""
import os, json, sys, re, datetime, urllib.request, urllib.parse
from collections import defaultdict

CUSTOMER_ID = "3190189170"
LOGIN_CUSTOMER_ID = "5098518843"
API = "https://googleads.googleapis.com/v20"
TOKEN_URL = "https://oauth2.googleapis.com/token"
OUT = os.path.join(os.path.dirname(__file__), "..", "data_ga_city.json")

def _creds():
    keys = ["GOOGLE_ADS_CLIENT_ID","GOOGLE_ADS_CLIENT_SECRET","GOOGLE_ADS_DEVELOPER_TOKEN","GOOGLE_ADS_REFRESH_TOKEN"]
    c = {k: os.environ.get(k,"") for k in keys}
    miss = [k for k,v in c.items() if not v]
    if miss: sys.exit("Missing credentials: " + ", ".join(miss))
    return c

def _access_token(c):
    data = urllib.parse.urlencode({
        "grant_type":"refresh_token","client_id":c["GOOGLE_ADS_CLIENT_ID"],
        "client_secret":c["GOOGLE_ADS_CLIENT_SECRET"],"refresh_token":c["GOOGLE_ADS_REFRESH_TOKEN"],
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data)
    return json.load(urllib.request.urlopen(req, timeout=30))["access_token"]

def gaql(token, c, query):
    """Run a GAQL query, auto-paginating; returns list of result dicts (camelCase nested)."""
    url = f"{API}/customers/{CUSTOMER_ID}/googleAds:search"
    out, page = [], None
    while True:
        body = {"query": query}
        if page: body["pageToken"] = page
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
            "Authorization": f"Bearer {token}", "developer-token": c["GOOGLE_ADS_DEVELOPER_TOKEN"],
            "login-customer-id": LOGIN_CUSTOMER_ID, "Content-Type": "application/json"})
        resp = json.load(urllib.request.urlopen(req, timeout=60))
        out += resp.get("results", [])
        page = resp.get("nextPageToken")
        if not page: break
    return out

def city_of(name):
    m = re.match(r'T[12]_([A-Za-z]+(?:_[A-Za-z]+)*)_SH_Exact_Local$', name)
    return m.group(1).replace('_',' ') if m else None

def city_of_any(name):
    # any local/city T1/T2 campaign → city (before the SH/STD/MH product marker)
    m = re.match(r'T[12]_(.+?)_(SH|STD|MH)_', name)
    return m.group(1).replace('_',' ') if m else None

def short_campaign(name, city):
    # drop the "T1_<City>_" prefix for compact display
    return re.sub(r'^T[12]_'+re.escape(city.replace(' ','_'))+r'_', '', name)

def derive_suggestion(g):
    bl, rl, ad, lp = g.get('budget_lost') or 0, g.get('rank_lost') or 0, g.get('ad_rel_drag') or 0, g.get('lp_drag') or 0
    if bl >= 0.10 and bl >= rl: return "Increase budget"
    if ad >= lp and ad >= 0.25: return "Fix ad relevance"
    if lp >= 0.25: return "Fix LP experience"
    if rl >= 0.40: return "Improve Ad Rank (bids / QS)"
    return "On track"

def main():
    c = _creds(); token = _access_token(c)
    today = datetime.date.today()
    start = today - datetime.timedelta(days=70)   # ~10 weeks, enough for W0 + W1 buckets
    qstart = today - datetime.timedelta(days=7)    # QS snapshot window (last week)
    ymd = lambda d: d.strftime('%Y-%m-%d')

    # 1) weekly campaign IS + cost
    rows = gaql(token, c, f"""
      SELECT campaign.name, campaign_budget.amount_micros, segments.week,
        metrics.search_impression_share, metrics.search_rank_lost_impression_share,
        metrics.search_budget_lost_impression_share, metrics.average_cpc,
        metrics.cost_micros, metrics.clicks
      FROM campaign
      WHERE campaign.advertising_channel_type = 'SEARCH'
        AND campaign.name LIKE '%_SH_Exact_Local'
        AND segments.date BETWEEN '{ymd(start)}' AND '{ymd(today)}'
      ORDER BY campaign.name, segments.week""")
    by_city_week = defaultdict(dict)   # city -> week -> metrics
    budget = {}
    for r in rows:
        name = r["campaign"]["name"]; city = city_of(name)
        if not city: continue
        wk = r["segments"]["week"]; m = r.get("metrics", {})
        budget[city] = int(r.get("campaignBudget", {}).get("amountMicros", 0) or 0)
        by_city_week[city][wk] = {
            'campaign': name,
            'is': float(m.get("searchImpressionShare", 0) or 0),
            'rank_lost': float(m.get("searchRankLostImpressionShare", 0) or 0),
            'budget_lost': float(m.get("searchBudgetLostImpressionShare", 0) or 0),
            'cpc': int(m.get("averageCpc", 0) or 0) / 1e6,
            'cost': int(m.get("costMicros", 0) or 0) / 1e6,
        }

    # 2) keyword quality components (current snapshot) → QS + ad-rel / LP drag per city
    krows = gaql(token, c, f"""
      SELECT campaign.name, metrics.impressions,
        ad_group_criterion.quality_info.quality_score,
        ad_group_criterion.quality_info.creative_quality_score,
        ad_group_criterion.quality_info.post_click_quality_score
      FROM keyword_view
      WHERE campaign.name LIKE '%_SH_Exact_Local'
        AND ad_group_criterion.status = 'ENABLED'
        AND segments.date BETWEEN '{ymd(qstart)}' AND '{ymd(today)}'""")
    q = defaultdict(lambda: {'imp':0,'qsw':0,'ad_bad':0,'lp_bad':0})
    for r in krows:
        city = city_of(r["campaign"]["name"])
        if not city: continue
        imp = int(r.get("metrics", {}).get("impressions", 0) or 0)
        qi = r.get("adGroupCriterion", {}).get("qualityInfo", {})
        qs = qi.get("qualityScore")
        a = q[city]; a['imp'] += imp
        if qs: a['qsw'] += qs * imp
        if qi.get("creativeQualityScore") == "BELOW_AVERAGE": a['ad_bad'] += imp
        if qi.get("postClickQualityScore") == "BELOW_AVERAGE": a['lp_bad'] += imp

    # 3) ALL enabled search campaigns (last 7 days) → per-city roster: impressions, clicks, CTR, spend, IS
    crows = gaql(token, c, f"""
      SELECT campaign.name, metrics.impressions, metrics.clicks, metrics.cost_micros,
        metrics.search_impression_share
      FROM campaign
      WHERE campaign.advertising_channel_type = 'SEARCH' AND campaign.status = 'ENABLED'
        AND segments.date BETWEEN '{ymd(today - datetime.timedelta(days=7))}' AND '{ymd(today)}'""")
    camps = defaultdict(lambda: defaultdict(lambda: {'impr':0,'clicks':0,'cost':0,'is':None}))
    for r in crows:
        name = r["campaign"]["name"]; cy = city_of_any(name)
        if not cy: continue
        m = r.get("metrics", {}); a = camps[cy][name]
        a['impr'] += int(m.get("impressions",0) or 0); a['clicks'] += int(m.get("clicks",0) or 0)
        a['cost'] += int(m.get("costMicros",0) or 0)/1e6
        if m.get("searchImpressionShare") is not None: a['is'] = float(m["searchImpressionShare"])

    prev = {}
    if os.path.exists(OUT):
        try: prev = json.load(open(OUT))
        except Exception: prev = {}

    res = {'_meta': {'source':'LIVE Google Ads pull (scripts/pull_ga_city.py) · SH Exact Local per city',
                     'account': CUSTOMER_ID, 'pulled': ymd(today),
                     'fields':'is/rank_lost/budget_lost/ad_rel_drag/lp_drag = share %; qs=Quality Score; cpc=₹; util=cost/budget %; _prev = prior week'}}
    for city, weeks in by_city_week.items():
        wk_sorted = sorted(weeks.keys())          # oldest → newest
        if not wk_sorted: continue
        w0 = weeks[wk_sorted[-1]]
        w1 = weeks[wk_sorted[-2]] if len(wk_sorted) >= 2 else {}
        a = q.get(city, {'imp':0,'qsw':0,'ad_bad':0,'lp_bad':0})
        imp = a['imp'] or 1
        g = {
            'is': round(w0['is'],4), 'is_prev': round(w1.get('is',0),4) if w1 else None,
            'rank_lost': round(w0['rank_lost'],4), 'rank_lost_prev': round(w1.get('rank_lost',0),4) if w1 else None,
            'budget_lost': round(w0['budget_lost'],4), 'budget_lost_prev': round(w1.get('budget_lost',0),4) if w1 else None,
            'qs': round(a['qsw']/imp,1) if a['imp'] else None,
            'ad_rel_drag': round(a['ad_bad']/imp,4) if a['imp'] else None,
            'lp_drag': round(a['lp_bad']/imp,4) if a['imp'] else None,
            'cpc': round(w0['cpc'],2), 'cpc_prev': round(w1.get('cpc',0),2) if w1 else None,
            'util': round(w0['cost']/((budget.get(city,0)/1e6*7) or 1),4) if budget.get(city) else None,
            'spend_wk': round(w0['cost'],0),
            'campaign': w0['campaign'],
        }
        # QS/drag have no API history → carry last run's current into *_prev
        p = prev.get(city, {})
        g['qs_prev'] = p.get('qs'); g['ad_rel_drag_prev'] = p.get('ad_rel_drag'); g['lp_drag_prev'] = p.get('lp_drag')
        g['suggestion'] = derive_suggestion(g)
        # full campaign roster for the city (last 7 days) — impressions, clicks, CTR, spend, IS
        g['campaigns'] = sorted([
            {'name': short_campaign(n, city), 'impr': v['impr'], 'clicks': v['clicks'],
             'ctr': round(v['clicks']/v['impr'],4) if v['impr'] else 0,
             'cost': round(v['cost'],0), 'is': round(v['is'],4) if v['is'] is not None else None}
            for n, v in camps.get(city, {}).items()
        ], key=lambda x: -x['impr'])
        res[city] = g

    json.dump(res, open(OUT,'w'), separators=(',',':'))
    print(f"wrote {OUT} · {len(res)-1} cities · pulled {ymd(today)}")

if __name__ == "__main__":
    main()
