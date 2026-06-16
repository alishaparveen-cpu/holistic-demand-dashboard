#!/usr/bin/env python3
"""LIVE Google Ads pull → data_ga_campaigns.json — per-campaign auction & outcomes for the
Google Campaigns view (campaigns.html). One record per enabled SEARCH campaign, matching the
view's CAMP shape. AUCTION metrics are exact from the API; OUTCOME = Google-Ads conversions +
cost-per-conversion (Loc%/CPLC/CPB aren't API fields, so we use conversions/CPA — API-only mode).

Per campaign:
  bud  daily budget ₹              ceil  null (manual-CPC ceiling not exposed per campaign)
  sp   latest-week spend ₹         d/v   [w0,w1] cost-per-conversion ₹ / conversions  (dt='cpp')
  cpc  [w0,w1,w2,w3] avg CPC ₹     is/bl/rl  [w0,w1] impr-share / lost-budget / lost-rank %
  qs   [w0,w1] Quality Score       ar/lp  [w0,w1] ad-relevance / LP-experience drag %
  util budget utilisation %        sug   derived next-action

QS/ad-rel/LP have no week history in the API → both weeks = current snapshot.
Run:  GOOGLE_ADS_*=... python3 scripts/pull_ga_campaigns.py
"""
import os, json, sys, re, datetime, urllib.request, urllib.parse
from collections import defaultdict

CUSTOMER_ID = "3190189170"; LOGIN_CUSTOMER_ID = "5098518843"
API = "https://googleads.googleapis.com/v21"; TOKEN_URL = "https://oauth2.googleapis.com/token"
OUT = os.path.join(os.path.dirname(__file__), "..", "data_ga_campaigns.json")

def _creds():
    keys = ["GOOGLE_ADS_CLIENT_ID","GOOGLE_ADS_CLIENT_SECRET","GOOGLE_ADS_DEVELOPER_TOKEN","GOOGLE_ADS_REFRESH_TOKEN"]
    c = {k: os.environ.get(k,"") for k in keys}
    miss = [k for k,v in c.items() if not v]
    if miss: sys.exit("Missing credentials: " + ", ".join(miss))
    return c

def _access_token(c):
    data = urllib.parse.urlencode({"grant_type":"refresh_token","client_id":c["GOOGLE_ADS_CLIENT_ID"],
        "client_secret":c["GOOGLE_ADS_CLIENT_SECRET"],"refresh_token":c["GOOGLE_ADS_REFRESH_TOKEN"]}).encode()
    return json.load(urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=data), timeout=30))["access_token"]

def gaql(token, c, query):
    url = f"{API}/customers/{CUSTOMER_ID}/googleAds:search"; out, page = [], None
    while True:
        body = {"query": query}
        if page: body["pageToken"] = page
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
            "Authorization": f"Bearer {token}", "developer-token": c["GOOGLE_ADS_DEVELOPER_TOKEN"],
            "login-customer-id": LOGIN_CUSTOMER_ID, "Content-Type": "application/json"})
        resp = json.load(urllib.request.urlopen(req, timeout=60))
        out += resp.get("results", []); page = resp.get("nextPageToken")
        if not page: break
    return out

def group_of(n):
    if re.search(r'brand', n, re.I): return 'brand'
    if n.startswith('ONL_LT') and 'HighIntent' in n: return 'highintent'
    if n.startswith('CC_Online') or n.startswith('ROI_Online'): return 'online'
    if re.search(r'_MH_', n): return 'mh'
    if re.search(r'_SH_Phrase_Local$', n) and n.startswith('T1_'): return 't1phrase'
    if n.startswith('T1_') and n.endswith('_SH_Exact'): return 'citylead'   # city-lead (no _Local)
    if n.startswith('T1_') and n.endswith('_SH_Exact_Local'): return 't1she'
    if n.startswith('T1_') and n.endswith('_STD_Exact_Local'): return 't1std'
    if n.startswith('T2_') and n.endswith('_SH_Exact_Local'): return 't2she'
    if n.startswith('T2_') and n.endswith('_STD_Exact_Local'): return 't2std'
    return 'online'   # fallback for any other online/national search campaign

def derive_suggestion(g):
    bl = (g['bl'][0] or 0); rl = (g['rl'][0] or 0); ad = (g['ar'][0] or 0); lp = (g['lp'][0] or 0); util = g['util'] or 0
    wks = sum(1 for v in (g['is'][0],) if v is not None)
    if g['sp'] and g['sp'] < 200: return "Hold — low spend"
    if util >= 0.95 and bl >= 0.08: return "Increase budget"
    if ad >= lp and ad >= 0.25: return "Fix ad relevance"
    if lp >= 0.25: return "Fix LP experience"
    if rl >= 0.45: return "Improve Ad Rank (bids / QS)"
    if bl >= 0.10: return "Increase budget"
    return "On track"

def main():
    c = _creds(); token = _access_token(c)
    today = datetime.date.today()
    start6 = today - datetime.timedelta(days=49)   # ~7 weeks → 4 complete + buffer
    qstart = today - datetime.timedelta(days=14)    # QS snapshot window
    ymd = lambda d: d.strftime('%Y-%m-%d')
    def complete(wk):
        try: return (datetime.date.fromisoformat(wk) + datetime.timedelta(days=7)) <= today
        except Exception: return False

    # 1) weekly per-campaign auction + cost + conversions
    rows = gaql(token, c, f"""
      SELECT campaign.name, campaign_budget.amount_micros, segments.week,
        metrics.search_impression_share, metrics.search_rank_lost_impression_share,
        metrics.search_budget_lost_impression_share, metrics.average_cpc,
        metrics.cost_micros, metrics.clicks, metrics.conversions
      FROM campaign
      WHERE campaign.advertising_channel_type='SEARCH' AND campaign.status='ENABLED'
        AND segments.date BETWEEN '{ymd(start6)}' AND '{ymd(today)}'
      ORDER BY campaign.name, segments.week""")
    cw = defaultdict(dict); budget = {}
    for r in rows:
        n = r["campaign"]["name"]; wk = r["segments"]["week"]; m = r.get("metrics", {})
        budget[n] = int(r.get("campaignBudget", {}).get("amountMicros", 0) or 0) / 1e6
        cw[n][wk] = {
            'is': float(m.get("searchImpressionShare", 0) or 0)*100,
            'rl': float(m.get("searchRankLostImpressionShare", 0) or 0)*100,
            'bl': float(m.get("searchBudgetLostImpressionShare", 0) or 0)*100,
            'cpc': int(m.get("averageCpc", 0) or 0) / 1e6,
            'cost': int(m.get("costMicros", 0) or 0) / 1e6,
            'conv': float(m.get("conversions", 0) or 0),
        }

    # 2) keyword quality components per campaign (current snapshot) → QS + ad-rel / LP drag
    krows = gaql(token, c, f"""
      SELECT campaign.name, metrics.impressions,
        ad_group_criterion.quality_info.quality_score,
        ad_group_criterion.quality_info.creative_quality_score,
        ad_group_criterion.quality_info.post_click_quality_score
      FROM keyword_view
      WHERE campaign.advertising_channel_type='SEARCH' AND ad_group_criterion.status='ENABLED'
        AND segments.date BETWEEN '{ymd(qstart)}' AND '{ymd(today)}'""")
    q = defaultdict(lambda: {'imp':0,'qsw':0,'qs_imp':0,'ad_bad':0,'lp_bad':0})
    for r in krows:
        n = r["campaign"]["name"]; imp = int(r.get("metrics", {}).get("impressions", 0) or 0)
        qi = r.get("adGroupCriterion", {}).get("qualityInfo", {}); a = q[n]; a['imp'] += imp
        # QS is impression-weighted over keywords that HAVE a score (unscored kws must not dilute toward 0)
        if qi.get("qualityScore"): a['qsw'] += qi["qualityScore"] * imp; a['qs_imp'] += imp
        if qi.get("creativeQualityScore") == "BELOW_AVERAGE": a['ad_bad'] += imp
        if qi.get("postClickQualityScore") == "BELOW_AVERAGE": a['lp_bad'] += imp

    NH = 6   # weeks of weekly history to keep (newest-first) for trend charts
    camps = []
    for n, weeks in cw.items():
        wks = [w for w in sorted(weeks.keys()) if complete(w)]    # oldest→newest complete weeks
        thin = False
        if len(wks) < 1:
            # enabled campaign with data only in the current (partial) week — e.g. just resumed.
            # Don't drop it: fall back to whatever weeks it has so it still appears (flagged thin).
            wks = sorted(weeks.keys())
            thin = True
        if len(wks) < 1: continue
        nf = wks[::-1][:NH]                       # newest-first, up to NH weeks
        rec = [weeks[w] for w in nf]              # rec[0]=latest week
        w0 = rec[0]
        arr = lambda fn: [fn(x) for x in rec]
        cpa = lambda x: round(x['cost']/x['conv']) if x['conv'] else None
        cpcA = arr(lambda x: round(x['cpc'], 2) if x['cpc'] else None)
        a = q.get(n, {'imp':0,'qsw':0,'qs_imp':0,'ad_bad':0,'lp_bad':0}); imp = a['imp'] or 0
        qs = round(a['qsw']/a['qs_imp'], 1) if a['qs_imp'] else None
        ar = round(a['ad_bad']/imp*100) if imp else None
        lp = round(a['lp_bad']/imp*100) if imp else None
        g = {
            'n': n, 'g': group_of(n), 'bud': round(budget.get(n, 0)), 'ceil': None,
            'sp': round(w0['cost']),
            'weeks_iso': nf,                       # ISO week-START dates, newest-first (W0,W1,…)
            'd': arr(cpa), 'v': arr(lambda x: round(x['conv'])),
            'cplc': [None, None],
            'cpc': cpcA,
            'spendH': arr(lambda x: round(x['cost'])),
            'qs': [qs, qs], 'is': arr(lambda x: round(x['is'])),
            'bl': arr(lambda x: round(x['bl'])), 'rl': arr(lambda x: round(x['rl'])),
            'ar': [ar, ar], 'lp': [lp, lp],
            'util': round(w0['cost']/(budget.get(n, 0)*7)*100) if budget.get(n) else None,
            'nweeks': len(wks), 'thin': thin,
        }
        g['sug'] = 'Hold — just resumed' if thin else derive_suggestion(g)
        camps.append(g)

    camps.sort(key=lambda x: -(x['sp'] or 0))
    all_complete = sorted({w for n in cw for w in cw[n] if complete(w)}, reverse=True)
    latest_wk = all_complete[0] if all_complete else ymd(today)
    gweeks = all_complete[:NH]                     # global timeline, newest-first
    out = {'_meta': {'source': 'LIVE Google Ads API (scripts/pull_ga_campaigns.py) · per-campaign auction & outcomes',
                     'account': CUSTOMER_ID, 'pulled': ymd(today), 'latest_week': latest_wk,
                     'weeks': gweeks, 'n': len(camps),
                     'note': 'API-only: outcomes = Google Ads conversions + cost-per-conversion (CPA); Loc%/CPLC/CPB not available via API. dt=cpp for all. weekly arrays (is/bl/rl/cpc/v/d/spendH) are newest-first; weeks_iso gives their week-START dates. QS/ad-rel/LP = current snapshot (no API week history).'},
           'campaigns': camps}
    json.dump(out, open(OUT, 'w'), separators=(',', ':'))
    print(f"wrote {OUT} · {len(camps)} campaigns · latest week {latest_wk}")


if __name__ == "__main__":
    main()
