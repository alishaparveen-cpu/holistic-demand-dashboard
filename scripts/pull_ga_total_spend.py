#!/usr/bin/env python3
"""Pull TOTAL Google Ads spend (all campaigns, all types) per ISO week → data_ga_total_spend.json.

This is the NETWORK Google spend for the channel-efficiency funnel — distinct from
data_ga_city_paid.json, which is Search-only AND only the enabled, city-name-mapped
campaigns. Here we want every campaign's cost so the efficiency view's Google spend
matches the marketing sheet.

NOTE: Google Ads `metrics.cost_micros` is NET media cost. The marketing (L0) sheet
reports GST-INCLUSIVE spend = net × 1.18 (verified: matches the sheet to the rupee
for every overlapping week). build_efficiency_rs.py applies that ×1.18.

Output: {"_meta":{...}, "weeks":["2026-06-08",...newest-first Mondays...], "net":[...]}
Auth: GOOGLE_ADS_CLIENT_ID/SECRET/REFRESH_TOKEN/DEVELOPER_TOKEN in env (e.g. ~/.allo_google_ads.env).
Run:  set -a; source ~/.allo_google_ads.env; set +a; python3 scripts/pull_ga_total_spend.py
"""
import os, sys, json, datetime, urllib.request, urllib.parse, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUSTOMER_ID = "3190189170"; LOGIN_CUSTOMER_ID = "5098518843"
API = "https://googleads.googleapis.com/v21"
OUT = os.path.join(ROOT, "data_ga_total_spend.json")
# pull a wide window (covers any 12-week efficiency window); builder picks what it needs
START = "2026-03-01"
END   = datetime.date.today().isoformat()

def _token():
    body = urllib.parse.urlencode({"grant_type":"refresh_token",
        "client_id":os.environ["GOOGLE_ADS_CLIENT_ID"],"client_secret":os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token":os.environ["GOOGLE_ADS_REFRESH_TOKEN"]}).encode()
    return json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", body))["access_token"]

def main():
    tok = _token()
    q = (f"SELECT segments.week, metrics.cost_micros FROM campaign "
         f"WHERE segments.date BETWEEN '{START}' AND '{END}'")
    req = urllib.request.Request(f"{API}/customers/{CUSTOMER_ID}/googleAds:search",
        data=json.dumps({"query": q}).encode(),
        headers={"Authorization":"Bearer "+tok,"developer-token":os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
                 "login-customer-id":LOGIN_CUSTOMER_ID,"Content-Type":"application/json"})
    by_wk = collections.defaultdict(float)
    resp = json.load(urllib.request.urlopen(req, timeout=120))
    for r in resp.get("results", []):
        by_wk[r["segments"]["week"]] += int(r["metrics"].get("costMicros", 0)) / 1e6  # segments.week = Monday
    weeks = sorted(by_wk, reverse=True)                                   # newest-first Mondays
    net = [round(by_wk[w]) for w in weeks]
    out = {"_meta": {"source": "Google Ads API · TOTAL net spend, all campaigns/types · customer "+CUSTOMER_ID,
                     "note": "net media cost; multiply ×1.18 for GST-inclusive (matches L0 sheet)",
                     "pulled": datetime.date.today().isoformat(), "range": [START, END]},
           "weeks": weeks, "net": net}
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    print(f"wrote {OUT} · {len(weeks)} weeks")
    for w, n in zip(weeks, net): print(f"  {w}: net ₹{n:,}  · gross ₹{round(n*1.18):,}")

if __name__ == "__main__":
    main()
