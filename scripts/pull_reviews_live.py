#!/usr/bin/env python3
"""Authoritative LIVE Google review counts — OUR clinics + every competitor — via DataForSEO Maps.
Keyed to the exact listing (competitor matched by place-id; our clinic matched by locality), so it can't
drift onto a wrong nearby listing the way a fuzzy search does.

Why: the grid review counts are unreliable — Kondapur showed 9 but is 994 live; Indiranagar 1,100 vs 747.
Reviews drive 'winnability', so they must be exact.

Auth: env DATAFORSEO_AUTH or ~/.allo_dfs_auth.
Output: data_reviews_live.json  { "our": {City|Loc: count}, "comp": {place_id: count} }
Run:  cd ~/hdd-live && python3 scripts/pull_reviews_live.py
Then: python3 scripts/build_competition_cube.py
"""
import os, json, time, urllib.request

AUTH = os.environ.get('DATAFORSEO_AUTH') or open(os.path.expanduser('~/.allo_dfs_auth')).read().strip()
URL  = 'https://api.dataforseo.com/v3/serp/google/maps/live/advanced'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def P(f): return os.path.join(ROOT, f)
def nm(s): return ''.join(ch for ch in str(s).lower() if ch.isalnum())
GAP = 2.2
CHECK = {'Bangalore|Jayanagar':841,'Hyderabad|Kondapur':994,'Bangalore|Indiranagar':747,
         'Bangalore|Arekere':683,'Bangalore|Koramangala':493,'Ahmedabad|Paldi':31}

def maps(keyword, lat=None, lng=None):
    """maps/live/advanced ALWAYS needs a location — coordinate if we have one, else India-wide."""
    body = [{'keyword': keyword, 'language_name': 'English', 'depth': 20}]
    if lat and lng: body[0]['location_coordinate'] = f'{lat},{lng},14'
    else:           body[0]['location_name'] = 'India'
    for attempt in range(5):
        try:
            req = urllib.request.Request(URL, method='POST', data=json.dumps(body).encode(),
                headers={'Authorization': 'Basic ' + AUTH, 'Content-Type': 'application/json'})
            r = json.load(urllib.request.urlopen(req, timeout=120))
            task = (r.get('tasks') or [{}])[0]
            if 'rates limit' in str(task.get('status_message','')).lower():
                print('   …rate limit, waiting 60s'); time.sleep(60); continue
            return (task.get('result') or [{}])[0].get('items') or []
        except Exception as e:
            if attempt == 0: print(f'   ! {type(e).__name__}: {str(e)[:80]}')
            time.sleep(4 * (attempt + 1))
    return []

def votes(item):
    return (item.get('rating') or {}).get('votes_count') or item.get('rating_count')

comp = json.load(open(P('data_competition.json')))['MH']['clinics']
DFS  = json.load(open(P('data_serp_dfs.json'))).get('MH', {})

# competitor place_id -> (name, lat, lng) from the crawl (for a coordinate-anchored, exact lookup)
cc = {}
for e in DFS.values():
    if not e: continue
    lat, lng = e.get('lat'), e.get('lng')
    for x in e.get('competitors', []):
        pid = x.get('place_id')
        if pid and pid not in cc and lat and lng: cc[pid] = (x.get('name'), lat, lng)

out = json.load(open(P('data_reviews_live.json'))) if os.path.exists(P('data_reviews_live.json')) else {'our':{}, 'comp':{}}
out.setdefault('our', {}); out.setdefault('comp', {})

print(f'--- OUR clinics ({len(comp)}) ---')
for i, (key, c) in enumerate(comp.items(), 1):
    if key in out['our']: continue
    city, loc = key.split('|', 1)
    items = [x for x in maps(f'Allo Health {loc} {city}') if x.get('type') == 'maps_search']
    pick = next((x for x in items if 'allo' in nm(x.get('title','')) and (nm(loc)[:6] in nm(x.get('title','')) or nm(loc)[:6] in nm(x.get('address','')))), None) \
        or next((x for x in items if 'allo' in nm(x.get('title',''))), None)
    out['our'][key] = votes(pick) if pick else None
    print(f'  {i:2}/{len(comp)}  {key:28} -> {out["our"][key]}')
    if i % 20 == 0: json.dump(out, open(P('data_reviews_live.json'),'w'), indent=1)
    time.sleep(GAP)

# unique competitor place_ids that appear in the cube
want = set()
for c in comp.values():
    for x in c.get('competitors', []):
        m = x.get('maps') or ''
        pid = m.split('cid=')[-1] if 'cid=' in m else (x.get('place_id') or '')
        if pid: want.add(pid)
print(f'--- COMPETITORS ({len(want)} unique) ---')
done = 0
for pid in want:
    if pid in out['comp']: continue
    name, lat, lng = cc.get(pid, (None, None, None))
    if not name:
        out['comp'][pid] = None; continue
    items = maps(name, lat, lng)
    hit = next((it for it in items if str(it.get('cid')) == str(pid) or str(it.get('place_id')) == str(pid)), None) \
        or next((it for it in items if nm(it.get('title',''))[:18] == nm(name)[:18]), None)
    out['comp'][pid] = votes(hit) if hit else None
    done += 1
    if done % 25 == 0:
        json.dump(out, open(P('data_reviews_live.json'),'w'), indent=1)
        print(f'  {done}/{len(want)} competitors …')
    time.sleep(GAP)

json.dump(out, open(P('data_reviews_live.json'),'w'), indent=1)
print('\n=== SELF-CHECK vs live-browser spot values (should match) ===')
for k, v in CHECK.items():
    print(f'  {k:28} browser={v:>5}  pull={out["our"].get(k)}')
print(f'\nwrote data_reviews_live.json · our {len([v for v in out["our"].values() if v])} · comp {len([v for v in out["comp"].values() if v])}')
