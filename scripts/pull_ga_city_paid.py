#!/usr/bin/env python3
"""LIVE Google Ads → data_ga_city_paid.json — CITY-level paid layer for the clinic funnel.
Google Ads campaigns target a whole CITY (one geo_target), so paid metrics can't go below
city. We aggregate every enabled SEARCH campaign to its city and emit weekly arrays (newest-first,
aligned to the dashboard's 12 weeks). The clinic funnel shows these as CITY context, with an
optional per-clinic allocation by booking share.

Per city, weekly:
  spend ₹ · clicks · loc_clicks · loc_pct % · is_pct % (impr-weighted) · budget ₹/d ·
  util % · conv (Google-Ads conversions) · impressions
Loc% = location click-types (CALLS 6, GET_DIRECTIONS 8, LOCATION_EXPANSION 9, LOC_CALL_TRACKING 58)
       ÷ total clicks — the local-campaign health metric.
Run:  GOOGLE_ADS_*=... python3 scripts/pull_ga_city_paid.py
"""
import os, json, sys, re, datetime, urllib.request, urllib.parse
from collections import defaultdict

CUSTOMER_ID = "3190189170"; LOGIN_CUSTOMER_ID = "5098518843"
API = "https://googleads.googleapis.com/v21"; TOKEN_URL = "https://oauth2.googleapis.com/token"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data_ga_city_paid.json")
WEEKS = ["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04",
         "2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23","2026-03-16","2026-03-09"]   # newest-first, dashboard grid
widx = {w: i for i, w in enumerate(WEEKS)}
NW = len(WEEKS)
LOC_CLICK_TYPES = {"CALLS", "GET_DIRECTIONS", "LOCATION_EXPANSION", "LOCATION_FORMAT_CALL_TRACKING"}
# Google-Ads campaign city token  →  dashboard city name (data_diagnostic "City|Clinic")
CITY_FIX = {"Vizag": "Visakhapatnam", "Mangalore": "Mangaluru", "Mysuru": "Mysuru", "Hubballi": "Hubli",
            "Navi_Mumbai": "Navi Mumbai"}
CITY_TOKENS = ["Navi_Mumbai","Bangalore","Chennai","Hyderabad","Mumbai","Thane","Pune","Coimbatore",
               "Ahmedabad","Aurangabad","Bhopal","Gandhinagar","Hubballi","Jaipur","Mangalore","Mysuru",
               "Nagpur","Nashik","Ranchi","Surat","Vizag","Amravati","Vijayawada"]

def _creds():
    keys = ["GOOGLE_ADS_CLIENT_ID","GOOGLE_ADS_CLIENT_SECRET","GOOGLE_ADS_DEVELOPER_TOKEN","GOOGLE_ADS_REFRESH_TOKEN"]
    c = {k: os.environ.get(k, "") for k in keys}
    miss = [k for k, v in c.items() if not v]
    if miss: sys.exit("Missing credentials: " + ", ".join(miss))
    return c

def _token(c):
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

def cat_of(name):
    u = "_" + name.upper() + "_"
    if "_STD_" in u or "_STI_" in u: return "STI"
    if "_MH_" in u: return "MH"
    if "_SH_" in u or "_ED_" in u or "_PE_" in u: return "SH"
    return "Other"

def city_of(name):
    for t in CITY_TOKENS:
        if re.search(rf"(^|_){re.escape(t)}(_|$)", name):
            return CITY_FIX.get(t, t.replace("_", " "))
    return None   # online/brand/national → no geo city

def main():
    c = _creds(); token = _token(c)
    today = datetime.date.today()
    start = datetime.date.fromisoformat(WEEKS[-1])
    end = datetime.date.fromisoformat(WEEKS[0]) + datetime.timedelta(days=6)
    ymd = lambda d: d.strftime("%Y-%m-%d")
    monday = lambda d: (d - datetime.timedelta(days=d.weekday())).isoformat()
    Z = lambda: [0.0]*NW
    cities = defaultdict(lambda: {k: Z() for k in
             ["spend","clicks","loc_clicks","is_w","is_d","impr","conv","budget_w","budget_n"]})
    CATS = ["STI","SH","MH","Other"]
    catacc = defaultdict(lambda: {ct: {"impr": Z(), "clicks": Z()} for ct in CATS})  # city → cat → impr/clicks

    # 1) weekly campaign metrics → city
    rows = gaql(token, c, f"""
      SELECT campaign.name, campaign_budget.amount_micros, segments.week,
        metrics.clicks, metrics.cost_micros, metrics.impressions, metrics.conversions,
        metrics.search_impression_share
      FROM campaign
      WHERE campaign.advertising_channel_type='SEARCH' AND campaign.status='ENABLED'
        AND segments.date BETWEEN '{ymd(start)}' AND '{ymd(end)}'""")
    for r in rows:
        n = r["campaign"]["name"]; city = city_of(n)
        if not city: continue
        wk = r["segments"]["week"]
        if wk not in widx: continue
        i = widx[wk]; m = r.get("metrics", {}); o = cities[city]
        cl = int(m.get("clicks", 0) or 0); cost = int(m.get("costMicros", 0) or 0)/1e6
        imp = int(m.get("impressions", 0) or 0); isv = float(m.get("searchImpressionShare", 0) or 0)
        bud = int(r.get("campaignBudget", {}).get("amountMicros", 0) or 0)/1e6
        o["spend"][i] += cost; o["clicks"][i] += cl; o["impr"][i] += imp
        o["conv"][i] += float(m.get("conversions", 0) or 0)
        o["is_w"][i] += isv*imp; o["is_d"][i] += imp
        o["budget_w"][i] += bud; o["budget_n"][i] += 1
        ca = catacc[city][cat_of(n)]; ca["impr"][i] += imp; ca["clicks"][i] += cl

    # 2) location click-types → loc clicks per city/week
    crows = gaql(token, c, f"""
      SELECT campaign.name, segments.week, segments.click_type, metrics.clicks
      FROM campaign
      WHERE campaign.advertising_channel_type='SEARCH' AND campaign.status='ENABLED'
        AND segments.date BETWEEN '{ymd(start)}' AND '{ymd(end)}'""")
    for r in crows:
        n = r["campaign"]["name"]; city = city_of(n)
        if not city: continue
        wk = r["segments"]["week"]
        if wk not in widx: continue
        if r["segments"].get("clickType") in LOC_CLICK_TYPES:
            cities[city]["loc_clicks"][widx[wk]] += int(r.get("metrics", {}).get("clicks", 0) or 0)

    out = {"_meta": {"source": "LIVE Google Ads API · city-level paid layer (campaigns→city)",
                     "weeks": WEEKS, "pulled": ymd(today),
                     "note": "Google Ads campaigns target a CITY (one geo_target) — these paid metrics cannot be split below city. loc_pct = location click-types ÷ total clicks. util = spend ÷ (avg daily budget × 7)."}}
    for city, o in cities.items():
        loc_pct = [round(o["loc_clicks"][i]/o["clicks"][i]*100, 1) if o["clicks"][i] else None for i in range(NW)]
        is_pct = [round(o["is_w"][i]/o["is_d"][i]*100, 1) if o["is_d"][i] else None for i in range(NW)]
        budget = [round(o["budget_w"][i]) if o["budget_n"][i] else None for i in range(NW)]
        util = [round(o["spend"][i]/(budget[i]*7)*100) if budget[i] else None for i in range(NW)]
        cpp = [round(o["spend"][i]/o["conv"][i]) if o["conv"][i] else None for i in range(NW)]
        eplc = [round(o["spend"][i]/o["loc_clicks"][i]) if o["loc_clicks"][i] else None for i in range(NW)]
        out[city] = {"spend": [round(x) for x in o["spend"]], "clicks": [round(x) for x in o["clicks"]],
                     "loc_clicks": [round(x) for x in o["loc_clicks"]], "loc_pct": loc_pct, "is_pct": is_pct,
                     "budget": budget, "util": util, "conv": [round(x) for x in o["conv"]],
                     "impr": [round(x) for x in o["impr"]], "cpp": cpp, "eplc": eplc,
                     "by_cat": {ct: {"impr": [round(x) for x in catacc[city][ct]["impr"]],
                                     "clicks": [round(x) for x in catacc[city][ct]["clicks"]]} for ct in CATS}}
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    n = len([k for k in out if k != "_meta"])
    print(f"wrote {OUT} · {n} cities")
    for city in sorted(k for k in out if k != "_meta")[:6]:
        o = out[city]; print(f"  {city:14} W0 spend ₹{o['spend'][0]} clicks {o['clicks'][0]} loc% {o['loc_pct'][0]} IS% {o['is_pct'][0]}")


if __name__ == "__main__":
    main()
