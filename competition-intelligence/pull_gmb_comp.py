#!/usr/bin/env python3
"""Fresh GMB Performance pull for the Competition Intelligence view — a ROLLING recent window
(independent of the diagnostic's frozen WEEKS, so data_gmb_insights.json is left untouched).
Writes data_gmb_comp.json keyed "City|Clinic" with per-week searches/calls/website/directions +
a `days` maturity array (GBP lags ~1 week, so the trailing week is usually incomplete → we mark it).

Auth: ~/.allo_gbp.json {client_id, client_secret, refresh_token} (business.manage scope).
"""
import os, sys, json, re, time, datetime, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = datetime.date(2026, 7, 24)
ACCOUNT = "accounts/104278284314268556784"
IMPR = ["BUSINESS_IMPRESSIONS_MOBILE_SEARCH","BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
        "BUSINESS_IMPRESSIONS_MOBILE_MAPS","BUSINESS_IMPRESSIONS_DESKTOP_MAPS"]
INTER = ["CALL_CLICKS","WEBSITE_CLICKS","BUSINESS_DIRECTION_REQUESTS"]
# rolling 8 recent Monday-weeks, newest first
_mon = TODAY - datetime.timedelta(days=TODAY.weekday())
WEEKS = [(_mon - datetime.timedelta(days=7*i)).isoformat() for i in range(8)]
WK_START = datetime.date.fromisoformat(WEEKS[-1])
WK_END   = datetime.date.fromisoformat(WEEKS[0]) + datetime.timedelta(days=6)
CRED = json.load(open(os.path.expanduser("~/.allo_gbp.json")))

def token():
    body = urllib.parse.urlencode({"client_id":CRED["client_id"],"client_secret":CRED["client_secret"],
        "refresh_token":CRED["refresh_token"],"grant_type":"refresh_token"}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", body) as r:
        return json.load(r)["access_token"]

def get(url, at):
    req = urllib.request.Request(url, headers={"Authorization":"Bearer "+at}); last=None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            last=e
            if e.code in (429,500,502,503,504): time.sleep(2*(attempt+1)); continue
            raise
    raise last

def list_locations(at):
    out, page = [], None
    while True:
        u = f"https://mybusinessbusinessinformation.googleapis.com/v1/{ACCOUNT}/locations?readMask=name,title&pageSize=100"
        if page: u += "&pageToken="+page
        d = get(u, at); out += d.get("locations", []); page = d.get("nextPageToken")
        if not page: break
    return out

def perf(loc_num, at):
    base = f"https://businessprofileperformance.googleapis.com/v1/locations/{loc_num}:fetchMultiDailyMetricsTimeSeries"
    params = [("dailyMetrics", m) for m in IMPR+INTER] + [
        ("dailyRange.start_date.year",WK_START.year),("dailyRange.start_date.month",WK_START.month),("dailyRange.start_date.day",WK_START.day),
        ("dailyRange.end_date.year",WK_END.year),("dailyRange.end_date.month",WK_END.month),("dailyRange.end_date.day",WK_END.day)]
    d = get(base+"?"+urllib.parse.urlencode(params), at)
    if "error" in d: return None
    wk_idx = {WEEKS[i]: i for i in range(len(WEEKS))}
    def monday(dt): return (dt - datetime.timedelta(days=dt.weekday())).isoformat()
    metric = {}; wk_days = [set() for _ in WEEKS]
    for s in d.get("multiDailyMetricTimeSeries",[{}])[0].get("dailyMetricTimeSeries",[]):
        name = s.get("dailyMetric"); arr=[0]*len(WEEKS)
        for p in s.get("timeSeries",{}).get("datedValues",[]):
            dd = p.get("date",{})
            if not dd: continue
            day = datetime.date(dd["year"],dd["month"],dd["day"]); mk = monday(day)
            if mk in wk_idx: arr[wk_idx[mk]] += int(p.get("value",0)); wk_days[wk_idx[mk]].add(day.isoformat())
        metric[name]=arr
    searches=[sum(metric.get(m,[0]*len(WEEKS))[i] for m in IMPR) for i in range(len(WEEKS))]
    inter   =[sum(metric.get(m,[0]*len(WEEKS))[i] for m in INTER) for i in range(len(WEEKS))]
    days    =[len(s) for s in wk_days]
    return {"searches":searches,"interactions":inter,"days":days,
            "calls":metric.get("CALL_CLICKS",[0]*len(WEEKS)),
            "website":metric.get("WEBSITE_CLICKS",[0]*len(WEEKS)),
            "directions":metric.get("BUSINESS_DIRECTION_REQUESTS",[0]*len(WEEKS))}

OVERRIDE = {
    "7222177911995979844":  "Navi Mumbai|Vashi", "13412576936814792533": "Navi Mumbai|Kharghar",
    "1678025661527334352":  "Ahmedabad|Paldi",  "16859390687673316202": "Mumbai|Andheri East",
    "16734770786722847016": "Bangalore|RT Nagar",
}

def main():
    at = token()
    comp = json.load(open(os.path.join(ROOT,"data_competition.json")))
    keys = sorted({k for cat in comp["_meta"]["cats"] for k in comp[cat]["clinics"]})   # City|Locality
    loc_by_clinic = { k.split("|")[1].strip().lower(): k for k in keys }
    from collections import defaultdict
    _bycity = defaultdict(list)
    for k in keys: _bycity[k.split("|")[0].strip().lower()].append(k)
    city_single = { c: ks[0] for c, ks in _bycity.items() if len(ks)==1 }
    locs = list_locations(at)
    print(f"GBP locations: {len(locs)} · clinic keys: {len(keys)} · weeks {WEEKS[0]}..{WEEKS[-1]}", flush=True)
    out = {"_meta":{"source":"Google Business Profile Performance API","weeks":WEEKS,
            "fields":"searches=impressions(search+maps); calls/website/directions=interactions; days=maturity(<7 incomplete)"}}
    matched, miss = 0, []
    for L in locs:
        title = L.get("title",""); num = L["name"].split("/")[-1]
        if num in OVERRIDE: key = OVERRIDE[num]
        else:
            t = re.sub(r"\ballo health\b", "", title, flags=re.I)
            parts = [p.strip().lower() for p in re.split(r"[,\-–|]", t) if p.strip()]
            if not parts: continue
            cand = parts[0]
            key = loc_by_clinic.get(cand) or city_single.get(cand) \
                  or next((v for kk,v in loc_by_clinic.items() if kk and (kk==cand or kk in cand or cand in kk)), None)
            if not key: miss.append(title[:40]); continue
        try: p = perf(num, at)
        except Exception: p = None
        if p: out[key]=p; matched+=1
    json.dump(out, open(os.path.join(ROOT,"data_gmb_comp.json"),"w"), separators=(",",":"))
    covered = set(k for k in out if k!="_meta")
    print(f"matched {matched} clinics → data_gmb_comp.json · no-listing: {len(set(keys)-covered)}", flush=True)

if __name__ == "__main__":
    main()
