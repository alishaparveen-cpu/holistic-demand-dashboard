#!/usr/bin/env python3
"""Geo-attributed MH keyword demand via DataForSEO.

The old matrix attributed a keyword to a city ONLY if the city name was in the text
("psychiatrist bangalore") and dumped every generic "psychiatrist near me / therapist near me"
query into one "National" bucket (~112k/mo of real local demand hidden there).

This pull fixes that: for a CITY-AGNOSTIC keyword set it asks DataForSEO for each keyword's search
volume PER CITY (location targeting). "therapist near me" then returns Bengaluru's share, Mumbai's
share, etc. — near-me demand bucketed back into cities, comparable to the geo-targeted Google-Ads
market size.

DataForSEO's /live endpoint accepts ONE city per request, and the plan allows ~12 requests/minute,
so this throttles to ~10/min (6s gap) and backs off 65s if it still trips the limit. Name failures
(Bangalore->Bengaluru, Aurangabad->Chhatrapati Sambhajinagar) retry with a fallback name.

Auth: env DATAFORSEO_AUTH (base64 "login:password") or ~/.allo_dfs_auth.
Output: data_mh_demand_geo.json  {city:{category:{keyword:monthly_sv}}, "_national":{...}}
"""
import os, json, time, urllib.request

AUTH = os.environ.get('DATAFORSEO_AUTH') or open(os.path.expanduser('~/.allo_dfs_auth')).read().strip()
POST = 'https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/task_post'
GET  = 'https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/task_get/'
LIVE = 'https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live'
GAP  = 6.0   # seconds between requests → ~10/min, safely under the 12/min limit

CITIES = {
 'Bangalore':     ['Bengaluru,Karnataka,India', 'Bangalore Urban,Karnataka,India'],
 'Mumbai':        ['Mumbai,Maharashtra,India'],
 'Pune':          ['Pune,Maharashtra,India'],
 'Hyderabad':     ['Hyderabad,Telangana,India'],
 'Chennai':       ['Chennai,Tamil Nadu,India'],
 'Navi Mumbai':   ['Navi Mumbai,Maharashtra,India', 'Thane,Maharashtra,India'],
 'Coimbatore':    ['Coimbatore,Tamil Nadu,India'],
 'Nagpur':        ['Nagpur,Maharashtra,India'],
 'Ranchi':        ['Ranchi,Jharkhand,India'],
 'Mysuru':        ['Mysuru,Karnataka,India', 'Mysore,Karnataka,India'],
 'Jaipur':        ['Jaipur,Rajasthan,India'],
 'Mangaluru':     ['Mangaluru,Karnataka,India', 'Mangalore,Karnataka,India'],
 'Nashik':        ['Nashik,Maharashtra,India', 'Nasik,Maharashtra,India'],
 'Aurangabad':    ['Chhatrapati Sambhajinagar,Maharashtra,India', 'Aurangabad,Maharashtra,India'],
 'Surat':         ['Surat,Gujarat,India'],
 'Bhopal':        ['Bhopal,Madhya Pradesh,India'],
 'Hubli':         ['Hubballi,Karnataka,India', 'Hubli,Karnataka,India'],
 'Ahmedabad':     ['Ahmedabad,Gujarat,India'],
 'Visakhapatnam': ['Visakhapatnam,Andhra Pradesh,India', 'Vizag,Andhra Pradesh,India'],
 'Gandhinagar':   ['Gandhinagar,Gujarat,India'],
 'Amravati':      ['Amravati,Maharashtra,India'],
 'Vadodara':      ['Vadodara,Gujarat,India', 'Baroda,Gujarat,India'],
 'Raipur':        ['Raipur,Chhattisgarh,India'],
 'Rajkot':        ['Rajkot,Gujarat,India'],
 'Kurnool':       ['Kurnool,Andhra Pradesh,India'],
 'Kochi':         ['Kochi,Kerala,India', 'Cochin,Kerala,India'],
 'Indore':        ['Indore,Madhya Pradesh,India'],
 'Tumkur':        ['Tumakuru,Karnataka,India', 'Tumkur,Karnataka,India'],
 '_national':     ['India'],
}

KEYWORDS = {
 'mental_health': ['mental health clinic','mental hospital near me','mental health hospital',
                   'mental health doctor near me','mental health treatment','mental health centre near me'],
 'therapy':       ['therapist near me','therapy near me','online therapy','couples therapy near me',
                   'therapy for anxiety','best therapist near me','trauma therapy near me',
                   'marriage therapy near me','cbt therapy'],
 'counselling':   ['counsellor near me','counselling near me','marriage counselling near me',
                   'relationship counselling near me','family counselling near me','online counsellor',
                   'career counselling near me'],
 'psychology':    ['psychologist','psychologist near me','best psychologist','best psychologist near me',
                   'child psychologist','clinical psychologist','counselling psychologist','online psychologist'],
 'psychiatrist':  ['psychiatrist near me','best psychiatrist near me','online psychiatrist',
                   'child psychiatrist near me','psychiatric hospital near me',
                   'psychiatrist for depression near me','psychiatrist doctor near me'],
 'conditions':    ['anxiety treatment','depression treatment','adhd treatment','ocd treatment',
                   'bipolar treatment','stress management','panic attack treatment','anxiety doctor near me',
                   'depression doctor near me','insomnia treatment','schizophrenia treatment'],
}
ALL_KW = [k for lst in KEYWORDS.values() for k in lst]
KW2CAT = {k: cat for cat, lst in KEYWORDS.items() for k in lst}

def _req(url, body=None):
    req = urllib.request.Request(url, method='POST' if body is not None else 'GET',
        data=(json.dumps(body).encode() if body is not None else None),
        headers={'Authorization': 'Basic ' + AUTH, 'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=180))

def one_city(location_name, kws=None):
    """Task-based Keyword-Planner pull: post the task, then poll task_get until ready. The task endpoint
    back-fills 12-month averages for low-volume terms that the /live endpoint returns as null.
    Returns rows on success, 'RETRY_NAME' if the location_name is invalid, None on hard fail."""
    body = [{'keywords': kws or ALL_KW, 'location_name': location_name, 'language_code': 'en'}]
    tid = None
    for attempt in range(5):
        try:
            task = (_req(POST, body).get('tasks') or [{}])[0]
            msg = str(task.get('status_message', '')).lower()
            if 'location_name' in msg or 'invalid field' in msg: return 'RETRY_NAME'
            if 'rates limit' in msg: print('     …rate limit, waiting 65s'); time.sleep(65); continue
            tid = task.get('id')
            if tid: break
        except Exception:
            time.sleep(5 * (attempt + 1))
    if not tid: return None
    for _ in range(40):                       # poll up to ~4 min for the task to finish
        time.sleep(6)
        try:
            task = (_req(GET + tid).get('tasks') or [{}])[0]
            if task.get('status_code') == 20000 and task.get('result'):
                return task['result']
        except Exception:
            pass
    return None

def live_fill(location_name, kws):
    """Fallback for keywords the task endpoint returns as null: the /live endpoint
    (impression-based estimate) fills most of them. Returns {keyword: search_volume}
    for the non-null results only."""
    out = {}
    if not kws: return out
    body = [{'keywords': kws, 'location_name': location_name, 'language_code': 'en'}]
    for attempt in range(4):
        try:
            task = (_req(LIVE, body).get('tasks') or [{}])[0]
            msg = str(task.get('status_message', '')).lower()
            if 'rates limit' in msg: print('     ...live rate limit, waiting 65s'); time.sleep(65); continue
            for row in (task.get('result') or []):
                sv = row.get('search_volume')
                if sv is not None: out[row.get('keyword')] = sv
            return out
        except Exception:
            time.sleep(5 * (attempt + 1))
    return out

def main():
    out, failed = {}, []
    for city, cands in CITIES.items():
        rows = None; used = None
        for loc in cands:
            res = one_city(loc)
            if res == 'RETRY_NAME':
                time.sleep(GAP); continue      # invalid name → throttle, try the next candidate
            rows = res; used = loc; break
        if not rows:
            failed.append(city); print(f'  {city:16} — not targetable'); time.sleep(GAP); continue
        vols = {}
        for row in rows:
            vols[row.get('keyword')] = row.get('search_volume')          # None when the API returns null
        # DataForSEO's live endpoint returns null unreliably even for known keywords → re-request the nulls
        for _ in range(2):
            nulls = [k for k in ALL_KW if vols.get(k) is None]
            if not nulls: break
            time.sleep(GAP)
            rr = one_city(used, nulls)
            if isinstance(rr, list):
                for row in rr:
                    if row.get('search_volume') is not None:
                        vols[row.get('keyword')] = row.get('search_volume')
        # /live fallback: the task endpoint drops whole keyword groups (psychology, psychiatrist) as null;
        # the /live endpoint recovers them. This restores the method the earlier pull used.
        nulls = [k for k in ALL_KW if vols.get(k) is None]
        if nulls:
            time.sleep(GAP)
            for kw, sv in live_fill(used, nulls).items():
                vols[kw] = sv
        cat_kw = {}
        for kw, sv in vols.items():
            cat = KW2CAT.get(kw)
            if cat: cat_kw.setdefault(cat, {})[kw] = sv or 0
        still_kw = [k for k in ALL_KW if not vols.get(k)]
        still = len(still_kw)
        out[city] = cat_kw
        nullstr = ', '.join(still_kw) if still_kw else '-'
        tot_city = sum(v for c in cat_kw.values() for v in c.values())
        print(f'  {city:16} total {tot_city:>7}/mo   ({used})  [{still} still null: {nullstr}]')
        time.sleep(GAP)                        # throttle to stay under 12/min

    json.dump(out, open('data_mh_demand_geo.json', 'w'), indent=1)
    tots = {c: sum(v for cat in d.values() for v in cat.values()) for c, d in out.items() if c != '_national'}
    print(f'\nwrote data_mh_demand_geo.json · {len(tots)} cities · {len(ALL_KW)} keywords · {sum(tots.values())}/mo total')
    if failed: print('SKIPPED (not targetable in Google Ads):', ', '.join(failed))
    print('\nCity demand (geo-attributed), high→low:')
    for c, t in sorted(tots.items(), key=lambda x: -x[1]):
        print(f'  {c:16} {t:>7}/mo')

if __name__ == '__main__':
    main()
