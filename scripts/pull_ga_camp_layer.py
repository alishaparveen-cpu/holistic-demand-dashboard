#!/usr/bin/env python3
"""LIVE Google Ads → data_ga_camp_layer.json — CAMPAIGN filter-layer for channel-view.html.

Distinct from pull_ga_campaigns.py (which feeds campaigns.html, 6-wk auction snapshot). This one
emits one row per enabled SEARCH campaign, weekly arrays newest-first ALIGNED TO THE CHANNEL-VIEW
GRID, with the filter dimensions parsed from the campaign name
(`T1_Bangalore_MH_Exact_Local` → tier · city · category · match-type · placement):
  tier   T1 | T2            city  Bangalore | … | None(national/brand)
  cat    STI | SH | MH | Other
  match  Exact | Phrase | Broad | —      place  Local | Online | Brand | Other
Per campaign, weekly: spend ₹ · impr · clicks · loc_clicks · conv · is_w (impr-weighted IS
numerator) · budget ₹/d. channel-view aggregates the filtered set into the same paid funnel.
Run:  GOOGLE_ADS_*=... python3 scripts/pull_ga_camp_layer.py
"""
import os, json, sys, re, datetime, urllib.request, urllib.parse

CUSTOMER_ID = "3190189170"; LOGIN_CUSTOMER_ID = "5098518843"
API = "https://googleads.googleapis.com/v21"; TOKEN_URL = "https://oauth2.googleapis.com/token"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data_ga_camp_layer.json")
WEEKS = ["2026-07-06","2026-06-29","2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23","2026-03-16","2026-03-09","2026-03-02","2026-02-23","2026-02-16","2026-02-09","2026-02-02","2026-01-26","2026-01-19","2026-01-12","2026-01-05"]
widx = {w: i for i, w in enumerate(WEEKS)}
NW = len(WEEKS)
LOC_CLICK_TYPES = {"CALLS", "GET_DIRECTIONS", "LOCATION_EXPANSION", "LOCATION_FORMAT_CALL_TRACKING"}
CITY_FIX = {"Vizag": "Visakhapatnam", "Mangalore": "Mangaluru", "Hubballi": "Hubli", "Navi_Mumbai": "Navi Mumbai"}
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

def tier_of(name):
    m = re.match(r"(?i)^T([12])[_\b]", name)
    return "T" + m.group(1) if m else "—"

def match_of(name):
    nl = name.lower()
    return "Exact" if "exact" in nl else "Phrase" if "phrase" in nl else "Broad" if "broad" in nl else "—"

def place_of(name):
    nl = name.lower()
    return "Brand" if "brand" in nl else "Online" if "online" in nl else "Local" if "local" in nl else "Other"

def city_of(name):
    for t in CITY_TOKENS:
        if re.search(rf"(^|_){re.escape(t)}(_|$)", name):
            return CITY_FIX.get(t, t.replace("_", " "))
    return None

def main():
    c = _creds(); token = _token(c)
    today = datetime.date.today()
    start = datetime.date.fromisoformat(WEEKS[-1]); end = datetime.date.fromisoformat(WEEKS[0]) + datetime.timedelta(days=6)
    ymd = lambda d: d.strftime("%Y-%m-%d"); Z = lambda: [0.0]*NW
    camps = {}

    def rec(n):
        if n not in camps:
            camps[n] = {"name": n, "tier": tier_of(n), "city": city_of(n), "cat": cat_of(n),
                        "match": match_of(n), "place": place_of(n),
                        "spend": Z(), "impr": Z(), "clicks": Z(), "loc_clicks": Z(), "conv": Z(),
                        "is_w": Z(), "budget": [None]*NW}
        return camps[n]

    rows = gaql(token, c, f"""
      SELECT campaign.name, campaign_budget.amount_micros, segments.week,
        metrics.clicks, metrics.cost_micros, metrics.impressions, metrics.conversions,
        metrics.search_impression_share
      FROM campaign
      WHERE campaign.advertising_channel_type='SEARCH' AND campaign.status='ENABLED'
        AND segments.date BETWEEN '{ymd(start)}' AND '{ymd(end)}'""")
    for r in rows:
        n = r["campaign"]["name"]; wk = r["segments"]["week"]
        if wk not in widx: continue
        i = widx[wk]; m = r.get("metrics", {}); o = rec(n)
        imp = int(m.get("impressions", 0) or 0); cl = int(m.get("clicks", 0) or 0)
        cost = int(m.get("costMicros", 0) or 0)/1e6; isv = float(m.get("searchImpressionShare", 0) or 0)
        bud = int(r.get("campaignBudget", {}).get("amountMicros", 0) or 0)/1e6
        o["spend"][i] += cost; o["impr"][i] += imp; o["clicks"][i] += cl
        o["conv"][i] += float(m.get("conversions", 0) or 0); o["is_w"][i] += isv*imp
        if bud: o["budget"][i] = round(bud)

    lrows = gaql(token, c, f"""
      SELECT campaign.name, segments.week, segments.click_type, metrics.clicks
      FROM campaign
      WHERE campaign.advertising_channel_type='SEARCH' AND campaign.status='ENABLED'
        AND segments.date BETWEEN '{ymd(start)}' AND '{ymd(end)}'""")
    for r in lrows:
        n = r["campaign"]["name"]; wk = r["segments"]["week"]
        if wk not in widx or n not in camps: continue
        if r["segments"].get("clickType") in LOC_CLICK_TYPES:
            camps[n]["loc_clicks"][widx[wk]] += int(r.get("metrics", {}).get("clicks", 0) or 0)

    arr = []
    for n, o in camps.items():
        if sum(o["spend"]) < 1 and sum(o["impr"]) < 1: continue
        arr.append({"name": n, "tier": o["tier"], "city": o["city"], "cat": o["cat"], "match": o["match"], "place": o["place"],
                    "spend": [round(x) for x in o["spend"]], "impr": [round(x) for x in o["impr"]],
                    "clicks": [round(x) for x in o["clicks"]], "loc_clicks": [round(x) for x in o["loc_clicks"]],
                    "conv": [round(x, 1) for x in o["conv"]], "is_w": [round(x, 1) for x in o["is_w"]], "budget": o["budget"]})
    arr.sort(key=lambda x: -sum(x["spend"]))
    out = {"_meta": {"source": "LIVE Google Ads API · campaign filter-layer for channel-view", "weeks": WEEKS,
                     "pulled": ymd(today), "note": "one row per enabled SEARCH campaign, aligned to the channel grid. is_w = impr-weighted IS numerator (÷ impr). dims parsed from campaign name."},
           "campaigns": arr}
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    print(f"wrote {OUT} · {len(arr)} campaigns")
    from collections import Counter
    for d in ("tier", "match", "place", "cat"):
        print(f"  {d}: {dict(Counter(x[d] for x in arr))}")


if __name__ == "__main__":
    main()
