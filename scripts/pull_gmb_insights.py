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
WEEKS=["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]
# derive the GBP pull window from WEEKS so it never drifts out of sync on a window shift
WK_START = datetime.date.fromisoformat(WEEKS[-1])                                  # oldest Monday
WK_END   = datetime.date.fromisoformat(WEEKS[0]) + datetime.timedelta(days=6)      # newest week's Sunday (GBP lag means recent days may be empty)

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
    metric = {}; wk_days = [set() for _ in WEEKS]   # distinct calendar days GBP actually reported, per week
    for s in d.get("multiDailyMetricTimeSeries",[{}])[0].get("dailyMetricTimeSeries",[]):
        name = s.get("dailyMetric"); arr=[0]*len(WEEKS)
        for p in s.get("timeSeries",{}).get("datedValues",[]):
            dd = p.get("date",{});
            if not dd: continue
            day = datetime.date(dd["year"],dd["month"],dd["day"]); mk = monday(day)
            if mk in wk_idx: arr[wk_idx[mk]] += int(p.get("value",0)); wk_days[wk_idx[mk]].add(day.isoformat())
        metric[name]=arr
    searches=[sum(metric.get(m,[0]*len(WEEKS))[i] for m in IMPR) for i in range(len(WEEKS))]
    inter   =[sum(metric.get(m,[0]*len(WEEKS))[i] for m in INTER) for i in range(len(WEEKS))]
    days    =[len(s) for s in wk_days]              # 0..7 days reported per week → dashboard flags incomplete (<7) trailing weeks
    return {"searches":searches,"interactions":inter,"days":days,
            "calls":metric.get("CALL_CLICKS",[0]*len(WEEKS)),
            "website":metric.get("WEBSITE_CLICKS",[0]*len(WEEKS)),
            "directions":metric.get("BUSINESS_DIRECTION_REQUESTS",[0]*len(WEEKS))}

# Explicit location-ID → "City|Locality" overrides for listings the title-matcher misses:
# several clinics carry a generic "Allo Health" title (no locality) or a tagline so long the
# locality token is buried. Resolved by inspecting storefrontAddress addressLines.
OVERRIDE = {
    "7222177911995979844":  "Navi Mumbai|Vashi",        # title "Allo Health"; addr "...Vashi"
    "13412576936814792533": "Navi Mumbai|Kharghar",     # long tagline title
    "1678025661527334352":  "Ahmedabad|Paldi",          # title "Allo Health"; addr "...Paldi"
    "16859390687673316202": "Mumbai|Andheri East",      # title "Allo Health"; addr "Andheri East"
    "16734770786722847016": "Bangalore|RT Nagar",       # title "Allo Health"; addr Ganganagar/CBI Rd
}

def main():
    at = token()
    diag = json.load(open(os.path.join(ROOT,"data_diagnostic.json")))
    keys = [k for k in diag if k!="_meta"]                      # "City|Clinic"
    loc_by_clinic = { k.split("|")[1].strip().lower(): k for k in keys }
    # city → key, ONLY for single-clinic cities. Many Allo listings are titled by CITY
    # ("Allo Health, Nashik …") not by locality ("Trimurti Chowk"), so a locality-only match misses them.
    from collections import defaultdict
    _bycity = defaultdict(list)
    for k in keys: _bycity[k.split("|")[0].strip().lower()].append(k)
    city_single = { c: ks[0] for c, ks in _bycity.items() if len(ks)==1 }
    locs = list_locations(at)
    print(f"GBP locations: {len(locs)} · clinic keys: {len(keys)}", flush=True)
    out, matched, miss = {"_meta":{"source":"Google Business Profile Performance API","weeks":WEEKS,
            "fields":"searches=impressions(search+maps); interactions=calls+website+directions"}}, 0, []
    for L in locs:
        title = L.get("title","")
        num = L["name"].split("/")[-1]
        if num in OVERRIDE:
            key = OVERRIDE[num]
        else:
            # location token = first segment after the brand; handles both
            # "Allo Health, <loc> - <tagline>" and "Allo Health - <city> | <tagline>".
            t = re.sub(r"\ballo health\b", "", title, flags=re.I)
            parts = [p.strip().lower() for p in re.split(r"[,\-–|]", t) if p.strip()]
            if not parts: continue
            cand = parts[0]
            key = loc_by_clinic.get(cand) or city_single.get(cand) \
                  or next((v for kk,v in loc_by_clinic.items() if kk and (kk==cand or kk in cand or cand in kk)), None)
            if not key: miss.append(title[:50]); continue
        try:
            p = perf(num, at)
        except Exception as e:
            p = None
        if p: out[key]=p; matched+=1; print(f"  {key}: searches wk0={p['searches'][0]} interactions wk0={p['interactions'][0]}", flush=True)
    json.dump(out, open(os.path.join(ROOT,"data_gmb_insights.json"),"w"), separators=(",",":"))
    covered = set(k for k in out if k!="_meta")
    no_listing = sorted(set(keys) - covered)
    print(f"\nmatched {matched} clinics · unmatched GBP titles: {len(miss)}")
    if miss: print("  unmatched listing titles:", miss)
    if no_listing: print(f"  clinics with NO GBP insights ({len(no_listing)}):", no_listing)

if __name__ == "__main__":
    main()
