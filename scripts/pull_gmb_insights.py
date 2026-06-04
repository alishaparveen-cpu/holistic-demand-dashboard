#!/usr/bin/env python3
"""Pull GMB profile Insights (Searches + Interactions) per clinic via the Google Business Profile
Performance API, weekly, aligned to the diagnostic's 12 Monday-weeks. Writes data_gmb_insights.json
keyed "City|Clinic". Auth: GBP_CLIENT_ID/SECRET/REFRESH_TOKEN in env (business.manage scope).

Searches      = BUSINESS_IMPRESSIONS_* (mobile/desktop search + maps)
Interactions  = CALL_CLICKS + WEBSITE_CLICKS + BUSINESS_DIRECTION_REQUESTS
"""
import os, sys, json, re, datetime, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCOUNT = "accounts/104278284314268556784"          # PERSONAL account holding the clinic locations
IMPR = ["BUSINESS_IMPRESSIONS_MOBILE_SEARCH","BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
        "BUSINESS_IMPRESSIONS_MOBILE_MAPS","BUSINESS_IMPRESSIONS_DESKTOP_MAPS"]
INTER = ["CALL_CLICKS","WEBSITE_CLICKS","BUSINESS_DIRECTION_REQUESTS"]
# 12 Monday-weeks, newest first (must match diagnostic WEEKS)
WEEKS = ["2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20",
         "2026-04-13","2026-04-06","2026-03-30","2026-03-23","2026-03-16","2026-03-09"]
WK_START = datetime.date(2026,3,9); WK_END = datetime.date(2026,5,31)

def token():
    body = urllib.parse.urlencode({"client_id":os.environ["GBP_CLIENT_ID"],
        "client_secret":os.environ["GBP_CLIENT_SECRET"],"refresh_token":os.environ["GBP_REFRESH_TOKEN"],
        "grant_type":"refresh_token"}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", body) as r:
        return json.load(r)["access_token"]

def get(url, at):
    req = urllib.request.Request(url, headers={"Authorization":"Bearer "+at})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def list_locations(at):
    out, page = [], None
    while True:
        u = f"https://mybusinessbusinessinformation.googleapis.com/v1/{ACCOUNT}/locations?readMask=name,title&pageSize=100"
        if page: u += "&pageToken="+page
        d = get(u, at)
        out += d.get("locations", [])
        page = d.get("nextPageToken")
        if not page: break
    return out

def perf(loc_num, at):
    base = f"https://businessprofileperformance.googleapis.com/v1/locations/{loc_num}:fetchMultiDailyMetricsTimeSeries"
    params = [("dailyMetrics", m) for m in IMPR+INTER] + [
        ("dailyRange.start_date.year",WK_START.year),("dailyRange.start_date.month",WK_START.month),("dailyRange.start_date.day",WK_START.day),
        ("dailyRange.end_date.year",WK_END.year),("dailyRange.end_date.month",WK_END.month),("dailyRange.end_date.day",WK_END.day)]
    d = get(base+"?"+urllib.parse.urlencode(params), at)
    if "error" in d: return None
    # bucket daily -> weekly Monday index
    wk_idx = {WEEKS[i]: i for i in range(len(WEEKS))}
    def monday(dt): return (dt - datetime.timedelta(days=dt.weekday())).isoformat()
    metric = {}
    for s in d.get("multiDailyMetricTimeSeries",[{}])[0].get("dailyMetricTimeSeries",[]):
        name = s.get("dailyMetric"); arr=[0]*len(WEEKS)
        for p in s.get("timeSeries",{}).get("datedValues",[]):
            dd = p.get("date",{});
            if not dd: continue
            day = datetime.date(dd["year"],dd["month"],dd["day"]); mk = monday(day)
            if mk in wk_idx: arr[wk_idx[mk]] += int(p.get("value",0))
        metric[name]=arr
    searches=[sum(metric.get(m,[0]*len(WEEKS))[i] for m in IMPR) for i in range(len(WEEKS))]
    inter   =[sum(metric.get(m,[0]*len(WEEKS))[i] for m in INTER) for i in range(len(WEEKS))]
    return {"searches":searches,"interactions":inter,
            "calls":metric.get("CALL_CLICKS",[0]*len(WEEKS)),
            "website":metric.get("WEBSITE_CLICKS",[0]*len(WEEKS)),
            "directions":metric.get("BUSINESS_DIRECTION_REQUESTS",[0]*len(WEEKS))}

def main():
    at = token()
    diag = json.load(open(os.path.join(ROOT,"data_diagnostic.json")))
    keys = [k for k in diag if k!="_meta"]                      # "City|Clinic"
    loc_by_clinic = { k.split("|")[1].strip().lower(): k for k in keys }
    locs = list_locations(at)
    print(f"GBP locations: {len(locs)} · clinic keys: {len(keys)}", flush=True)
    out, matched, miss = {"_meta":{"source":"Google Business Profile Performance API","weeks":WEEKS,
            "fields":"searches=impressions(search+maps); interactions=calls+website+directions"}}, 0, []
    for L in locs:
        m = re.search(r"Allo Health,?\s*([^-–|]+)", L.get("title",""))
        if not m: continue
        loc = m.group(1).strip().lower()
        key = loc_by_clinic.get(loc) or next((v for kk,v in loc_by_clinic.items() if kk==loc or kk in loc or loc in kk), None)
        if not key: miss.append(L.get("title","")[:40]); continue
        num = L["name"].split("/")[-1]
        try:
            p = perf(num, at)
        except Exception as e:
            p = None
        if p: out[key]=p; matched+=1; print(f"  {key}: searches wk0={p['searches'][0]} interactions wk0={p['interactions'][0]}", flush=True)
    json.dump(out, open(os.path.join(ROOT,"data_gmb_insights.json"),"w"), separators=(",",":"))
    print(f"\nmatched {matched} clinics · unmatched titles: {len(miss)}")

if __name__ == "__main__":
    main()
