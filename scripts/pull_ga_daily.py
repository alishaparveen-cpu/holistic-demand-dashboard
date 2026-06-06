#!/usr/bin/env python3
"""LIVE Google Ads DAILY pull → data_ga_daily.json — powers the marketing timeline / date-range.

Per enabled SEARCH campaign matching T1/T2_<City>_<SH|STD|MH>_*, pulls DAILY:
  impressions, clicks, cost, conversions  (last ~120 days)
Tagged by city + product (SH/STD/MH) so the UI can build any date-range window and
compare SH vs MH or city vs city. Conversions = Google-Ads-tracked conversion actions
(labelled as such in the UI — the exact lead/booking funnel comes from the Redshift gclid join).

Run:  source ~/.allo_google_ads.env && python3 scripts/pull_ga_daily.py
Reuses the same 4 OAuth creds as pull_ga_city.py.
"""
import os, json, sys, re, datetime, urllib.request, urllib.parse
from collections import defaultdict

CUSTOMER_ID = "3190189170"; LOGIN_CUSTOMER_ID = "5098518843"
API = "https://googleads.googleapis.com/v20"; TOKEN_URL = "https://oauth2.googleapis.com/token"
OUT = os.path.join(os.path.dirname(__file__), "..", "data_ga_daily.json")
DAYS_BACK = 120

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

def parse_name(name):
    # city: T1/T2_<City>_... → city; otherwise a national/online campaign
    m = re.match(r'T[12]_([A-Za-z]+(?:_[A-Za-z]+)*?)_(?:SH|STD|MH|ED|PE)_', name)
    city = m.group(1).replace('_',' ') if m else 'National / Online'
    u = name.upper()
    if re.search(r'(^|_)MH(_|$)', u) or 'MENTAL' in u: prod='MH'
    elif re.search(r'(^|_)STD(_|$)', u): prod='STD'
    elif re.search(r'(^|_)ED(_|$)', u): prod='ED'
    elif re.search(r'(^|_)PE(_|$)', u): prod='PE'
    elif 'BRAND' in u: prod='Brand'
    elif re.search(r'(^|_)SH(_|$)', u): prod='SH'
    else: prod='Other'
    return (city, prod)

def main():
    c = _creds(); token = _access_token(c)
    today = datetime.date.today(); start = today - datetime.timedelta(days=DAYS_BACK)
    ymd = lambda d: d.strftime('%Y-%m-%d')
    rows = gaql(token, c, f"""
      SELECT campaign.name, segments.date, metrics.impressions, metrics.clicks,
        metrics.cost_micros, metrics.conversions
      FROM campaign
      WHERE campaign.advertising_channel_type = 'SEARCH' AND campaign.status = 'ENABLED'
        AND segments.date BETWEEN '{ymd(start)}' AND '{ymd(today)}'
      ORDER BY campaign.name, segments.date""")
    # camp -> date -> metrics
    camp = defaultdict(lambda: defaultdict(lambda: {'impr':0,'clicks':0,'cost':0.0,'conv':0.0}))
    meta = {}
    alldates = set()
    for r in rows:
        name = r["campaign"]["name"]; city, prod = parse_name(name)
        if not city: continue
        d = r["segments"]["date"]; m = r.get("metrics", {})
        a = camp[name][d]
        a['impr'] += int(m.get("impressions",0) or 0); a['clicks'] += int(m.get("clicks",0) or 0)
        a['cost'] += int(m.get("costMicros",0) or 0)/1e6; a['conv'] += float(m.get("conversions",0) or 0)
        meta[name] = (city, prod); alldates.add(d)
    days = sorted(alldates)
    di = {d:i for i,d in enumerate(days)}
    campaigns = []
    for name, byd in camp.items():
        city, prod = meta[name]
        impr=[0]*len(days); clk=[0]*len(days); cost=[0.0]*len(days); conv=[0.0]*len(days)
        for d, a in byd.items():
            i = di[d]; impr[i]=a['impr']; clk[i]=a['clicks']; cost[i]=round(a['cost'],2); conv[i]=round(a['conv'],2)
        campaigns.append({'name':re.sub(r'^T[12]_'+re.escape(city.replace(' ','_'))+r'_','',name),
            'full':name,'city':city,'product':prod,'impr':impr,'clicks':clk,'cost':cost,'conv':conv})
    campaigns.sort(key=lambda x:-sum(x['impr']))
    out = {'_meta':{'source':'LIVE Google Ads daily pull (scripts/pull_ga_daily.py)','account':CUSTOMER_ID,
        'pulled':ymd(today),'days_back':DAYS_BACK,
        'note':'conv = Google-Ads-tracked conversions (not the same as Redshift bookings). product = SH/STD/MH from campaign name.'},
        'days':days,'campaigns':campaigns}
    json.dump(out, open(OUT,'w'), separators=(',',':'))
    prods = defaultdict(int)
    for x in campaigns: prods[x['product']]+=1
    print(f"wrote {OUT} · {len(campaigns)} campaigns · {len(days)} days · products {dict(prods)}")

if __name__ == "__main__":
    main()
