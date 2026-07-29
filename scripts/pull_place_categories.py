#!/usr/bin/env python3
"""Pull each competitor's TRUE primary Google category (place-id level), to kill query-matched mislabels.

The maps crawl for "psychiatrist" tags whoever it returns with the SEARCHED category — so "Tarot with Jyoti"
comes back as "Psychiatrist". To get the real category we look each business up by its own NAME (a name search
is not category-biased) and read the category Google shows on its own listing, plus additional_categories.

Scope: the rivals that actually appear in data_competition.json (MH) — a few hundred, not all 3,713 crawl hits.
Resumable: re-run to continue; already-pulled names are skipped. Throttled ~10/min for the 12/min live limit.

Auth: env DATAFORSEO_AUTH (base64 "login:password") or ~/.allo_dfs_auth.
Output: data_place_categories.json  { normalized_name: {name, category, additional_categories} }
Then rebuild the cube — build_competition_cube.py will prefer this authoritative primary category.
"""
import os, json, time, urllib.request

AUTH = os.environ.get('DATAFORSEO_AUTH') or open(os.path.expanduser('~/.allo_dfs_auth')).read().strip()
URL  = 'https://api.dataforseo.com/v3/serp/google/maps/live/advanced'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # hdd-live (parent of scripts/)
def P(f): return os.path.join(ROOT, f)
def nm(s): return ''.join(ch for ch in str(s).lower() if ch.isalnum())

# 1) target set = competitor names shown across ALL categories (SH + STI + MH), mapped to a place_id + clinic
#    coord from the crawl. A business's primary category is intrinsic (not category-specific), so one lookup
#    per distinct name covers it wherever it appears — this widens the old MH-only scope so STI/SH diagnostics
#    labs stop falling back to the flaky crawl category ("Hospice").
_ALLCUBE = json.load(open(P('data_competition.json')))
_DFSALL = json.load(open(P('data_serp_dfs.json')))
want = {}; coord = {}; rival_city = {}
for _CAT in ('SH', 'STI', 'MH'):
    comp = _ALLCUBE.get(_CAT, {}).get('clinics', {})
    for c in comp.values():
        _city = c.get('city')
        for x in c.get('competitors', []):
            if x.get('name'):
                k = nm(x['name']); want[k] = x['name']
                if _city and k not in rival_city: rival_city[k] = _city
    for e in (_DFSALL.get(_CAT, {}) or {}).values():
        if not e: continue
        lat, lng = e.get('lat'), e.get('lng')
        for x in e.get('competitors', []):
            k = nm(x.get('name', ''))
            if k in want and k not in coord and lat and lng:
                coord[k] = (x['name'], x.get('place_id'), lat, lng)
targets = {k: coord[k] for k in want if k in coord}
# rivals with NO crawl coordinate → look them up by name + their city (location_name) instead
for k in want:
    if k not in targets and k in rival_city:
        targets[k] = (want[k], None, None, None, rival_city[k])   # 5-tuple → city fallback
print(f'{len(want)} distinct rivals in the cube · {len(targets)} to look up (coord + city fallback)')

out = json.load(open(P('data_place_categories.json'))) if os.path.exists(P('data_place_categories.json')) else {}

def maps_name(name, lat, lng, loc_name=None):
    body = [{'keyword': name, 'language_name': 'English', 'depth': 5}]
    if lat and lng: body[0]['location_coordinate'] = f'{lat},{lng},14'
    else:           body[0]['location_name'] = f'{loc_name},India' if loc_name else 'India'
    for attempt in range(5):
        try:
            req = urllib.request.Request(URL, method='POST', data=json.dumps(body).encode(),
                headers={'Authorization': 'Basic ' + AUTH, 'Content-Type': 'application/json'})
            r = json.load(urllib.request.urlopen(req, timeout=120))
            task = (r.get('tasks') or [{}])[0]
            if 'rates limit' in str(task.get('status_message', '')).lower():
                print('   …rate limit, waiting 65s'); time.sleep(65); continue
            return (task.get('result') or [{}])[0].get('items') or []
        except Exception:
            time.sleep(4 * (attempt + 1))
    return []

done = 0
for k, tgt in targets.items():
    if k in out and out[k].get('category'): continue   # re-attempt entries that came back null
    name, pid, lat, lng = tgt[0], tgt[1], tgt[2], tgt[3]
    loc_name = tgt[4] if len(tgt) > 4 else None
    items = [i for i in maps_name(name, lat, lng, loc_name) if i.get('type') == 'maps_search']
    # pick the item that matches this business (by place_id, else by name), take ITS real category
    hit = None
    for i in items:
        if pid and i.get('place_id') == pid: hit = i; break
    if not hit:
        for i in items:
            if nm(i.get('title', ''))[:18] == k[:18]: hit = i; break
    if not hit and items: hit = items[0]
    out[k] = {'name': name,
              'category': (hit or {}).get('category'),
              'additional_categories': (hit or {}).get('additional_categories') or []}
    done += 1
    if done % 20 == 0:
        json.dump(out, open(P('data_place_categories.json'), 'w'), indent=1)
        print(f'  {done} pulled (checkpoint) · e.g. {name[:30]} -> {out[k]["category"]}')
    time.sleep(6)   # ~10/min, under the 12/min live limit

json.dump(out, open(P('data_place_categories.json'), 'w'), indent=1)
print(f'\nwrote data_place_categories.json · {len(out)} businesses with true primary category')
# quick look at the spam catches
for k in list(out)[:0]: pass
bad = [(v['name'], v['category']) for v in out.values() if v['category'] and not any(t in (v['category'] or '').lower() for t in ('psychiatr','psycholog','counsel','therap','mental','rehab'))]
print(f'{len(bad)} of them have a NON-mental-health primary category (will be excluded on next cube build). Examples:')
for n, c in bad[:15]: print(f'   {n[:36]:36} -> {c}')
