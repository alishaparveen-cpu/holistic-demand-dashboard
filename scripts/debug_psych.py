#!/usr/bin/env python3
"""Isolate why psychology keywords come back 0. Pulls a few keywords for India and prints the RAW
search_volume DataForSEO returns (null vs a number) — psychiatrist is the control that we know works."""
import os, json, urllib.request
AUTH = os.environ.get('DATAFORSEO_AUTH') or open(os.path.expanduser('~/.allo_dfs_auth')).read().strip()
URL  = 'https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live'
KWS  = ['psychologist','psychologist near me','best psychologist','child psychologist',
        'psychiatrist','psychiatrist near me','therapist near me']   # last 3 = known-working controls
body = [{'keywords': KWS, 'location_name': 'India', 'language_code': 'en'}]
req = urllib.request.Request(URL, method='POST', data=json.dumps(body).encode(),
        headers={'Authorization':'Basic '+AUTH,'Content-Type':'application/json'})
r = json.load(urllib.request.urlopen(req, timeout=120))
task = (r.get('tasks') or [{}])[0]
print('status:', task.get('status_code'), task.get('status_message'))
for row in (task.get('result') or []):
    print(f"  {row.get('keyword'):32} search_volume={row.get('search_volume')!r:>8}  cpc={row.get('cpc')}  comp={row.get('competition')}")
