#!/usr/bin/env python3
"""LIVE Google Ads → data_hadapsar_google_geo.json — CLINIC-level paid reach from the
LOCATION ASSET performance report (the same numbers as Google Ads UI → Assets → Location).

Hadapsar (Savali_Allo_Clinic) place_id: ChIJxSuRryjDwjsRbkMT2TxHpvc
Confirmed via GBP API: locations/18428812500995344552 → metadata.placeId

Weekly (Monday, newest-first, 13 weeks) × category (SH/STD/MH/ED/Brand/Other from campaign name):
  impressions · clicks · ctr
Run: source ~/.allo_google_ads.env && python3 scripts/pull_hadapsar_google_asset.py
"""
import os, json, sys, re, datetime, urllib.request, urllib.parse, urllib.error
from collections import defaultdict

CUSTOMER_ID = "3190189170"; LOGIN_CUSTOMER_ID = "5098518843"
API = "https://googleads.googleapis.com/v21"; TOKEN_URL = "https://oauth2.googleapis.com/token"
OUT = os.path.join(os.path.dirname(__file__), "..", "data_hadapsar_google_geo.json")
HADAPSAR_PLACE_ID = "ChIJxSuRryjDwjsRbkMT2TxHpvc"
WEEKS = ["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11",
         "2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]
widx = {w: i for i, w in enumerate(WEEKS)}; NW = len(WEEKS)
CATS = ['STI','SH','MH','Other']

def cat_of(name):
    u = name.upper()
    if re.search(r'(^|_)MH(_|$)', u) or 'MENTAL' in u: return 'MH'
    if re.search(r'(^|_)STD(_|$)', u) or re.search(r'(^|_)STI(_|$)', u): return 'STI'
    if re.search(r'(^|_)(SH|ED|PE)(_|$)', u) or 'SEXUAL' in u: return 'SH'
    return 'Other'

def _creds():
    keys = ["GOOGLE_ADS_CLIENT_ID","GOOGLE_ADS_CLIENT_SECRET","GOOGLE_ADS_DEVELOPER_TOKEN","GOOGLE_ADS_REFRESH_TOKEN"]
    c = {k: os.environ.get(k,"") for k in keys}
    miss = [k for k,v in c.items() if not v]
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
        try:
            resp = json.load(urllib.request.urlopen(req, timeout=120))
        except urllib.error.HTTPError as e:
            sys.exit("GAQL error: " + e.read().decode()[:400])
        out += resp.get("results", []); page = resp.get("nextPageToken")
        if not page: break
    return out

def main():
    c = _creds(); token = _token(c)
    start = datetime.date.fromisoformat(WEEKS[-1])
    end = datetime.date.fromisoformat(WEEKS[0]) + datetime.timedelta(days=6)
    ymd = lambda d: d.strftime("%Y-%m-%d")

    # 1) Find Hadapsar location asset id(s) by place_id
    arows = gaql(token, c, "SELECT asset.id, asset.location_asset.place_id FROM asset WHERE asset.type = LOCATION")
    hap_ids = {r["asset"]["id"] for r in arows
               if (r["asset"].get("locationAsset") or {}).get("placeId") == HADAPSAR_PLACE_ID}
    if not hap_ids: sys.exit(f"No location asset with place_id {HADAPSAR_PLACE_ID}")
    print(f"Hadapsar asset ids: {sorted(hap_ids)}")

    # 2) Campaign metrics segmented by served asset × week
    rows = gaql(token, c, f"""
      SELECT campaign.name, campaign.advertising_channel_type, campaign.status, segments.week,
        segments.asset_interaction_target.asset, segments.asset_interaction_target.interaction_on_this_asset,
        metrics.impressions, metrics.clicks
      FROM campaign
      WHERE campaign.advertising_channel_type = SEARCH AND campaign.status = ENABLED
        AND segments.date BETWEEN '{ymd(start)}' AND '{ymd(end)}'""")

    def Z(): return {m:[0]*NW for m in ('impr','clicks')}
    bycat = {ct: Z() for ct in CATS}; tot = Z()
    for r in rows:
        seg = r["segments"]; ait = seg.get("assetInteractionTarget") or {}
        aid = (ait.get("asset") or "").split("/")[-1]
        if aid not in hap_ids: continue
        name = r["campaign"]["name"]
        # Keep city-local campaigns only (T1_/T2_ prefix — clinic-level, not national/online)
        if not name.startswith(("T1_", "T2_")): continue
        wk = seg.get("week")
        if wk not in widx: continue
        i = widx[wk]; ct = cat_of(name); m = r.get("metrics", {})
        clk = int(m.get("clicks",0) or 0); imp = int(m.get("impressions",0) or 0)
        on_asset = ait.get("interactionOnThisAsset", False)
        bycat[ct]['clicks'][i] += clk; tot['clicks'][i] += clk
        if not on_asset:
            bycat[ct]['impr'][i] += imp; tot['impr'][i] += imp

    ctr = lambda dd: [round(dd['clicks'][i]/dd['impr'][i]*100,1) if dd['impr'][i] else None for i in range(NW)]
    out = {"_meta": {"weeks": WEEKS, "place_id": HADAPSAR_PLACE_ID, "asset_ids": sorted(hap_ids),
            "source": "LIVE Google Ads · location-asset performance (Assets→Location), Hadapsar GBP asset",
            "note": "Per-clinic paid reach = the Hadapsar location asset's served impressions, CITY-LOCAL campaigns only (T1_/T2_; national/online + Brand excluded). clicks = clicks on the ad + clicks on the asset. category from campaign name (STI/SH/MH/Other). Pune city-level campaigns serve all Pune clinics as location assets; impressions here = the rows filtered to the Hadapsar asset ID."},
        "total": {**tot, "ctr": ctr(tot)},
        "by_cat": {ct: {**bycat[ct], "ctr": ctr(bycat[ct])} for ct in CATS}}
    json.dump(out, open(OUT,"w"), separators=(",",":"))
    print(f"wrote {OUT}")
    for i in (0,1):
        print(f"  {WEEKS[i]}: impr {tot['impr'][i]} clicks {tot['clicks'][i]} ctr {out['total']['ctr'][i]}")
    print("  by cat (latest): " + " · ".join(f"{ct} {bycat[ct]['impr'][0]}i/{bycat[ct]['clicks'][0]}c" for ct in CATS if bycat[ct]['impr'][0]))

if __name__ == "__main__":
    main()
