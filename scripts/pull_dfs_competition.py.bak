#!/usr/bin/env python3
"""Crawl local map-pack competition per clinic via DataForSEO Maps (coordinate search).
For each clinic coordinate + each category keyword, pull the Google Maps local pack:
competitors with rating, review count, category, EXACT coords (→ distance from clinic).

Auth: token in ~/.allo_dfs_auth (Basic). Input: /tmp/clinic_coords.tsv (city,locality,name,lat,lng).
Output: data_serp_dfs.json  {cat:{ 'City|Locality': {our:{...}, competitors:[...]} }}
"""
import os, json, time, math, urllib.request, urllib.error

AUTH = open(os.path.expanduser('~/.allo_dfs_auth')).read().strip()
URL = 'https://api.dataforseo.com/v3/serp/google/maps/live/advanced'
KEYWORDS = {'SH': 'sexologist', 'STI': 'std testing clinic', 'MH': 'psychiatrist'}

def hav(a, b, c, dd):
    R = 6371; p1, p2 = math.radians(a), math.radians(c)
    dphi = math.radians(c - a); dl = math.radians(dd - b)
    x = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(R * 2 * math.asin(math.sqrt(x)), 1)

def maps(keyword, lat, lng):
    body = [{'keyword': keyword, 'location_coordinate': f'{lat},{lng},14',
             'language_name': 'English', 'depth': 20}]
    for attempt in range(5):
        try:
            req = urllib.request.Request(URL, method='POST', data=json.dumps(body).encode(),
                headers={'Authorization': 'Basic ' + AUTH, 'Content-Type': 'application/json'})
            r = json.load(urllib.request.urlopen(req, timeout=120))
            t = (r.get('tasks') or [{}])[0]
            return (t.get('result') or [{}])[0].get('items') or []
        except Exception:
            time.sleep(3 * (attempt + 1))   # backoff on any error incl connection reset
    return []

def main():
    clinics = []
    for ln in open('/tmp/clinic_coords.tsv'):
        p = ln.rstrip('\n').split('\t')
        if len(p) >= 5 and p[3] and p[4]:
            try: clinics.append((p[0], p[1], p[2], float(p[3]), float(p[4])))
            except ValueError: pass
    outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data_serp_dfs.json')
    out = json.load(open(outpath)) if os.path.exists(outpath) else {c: {} for c in KEYWORDS}
    for c in KEYWORDS: out.setdefault(c, {})
    total = len(clinics) * len(KEYWORDS); done = 0
    for city, loc, name, lat, lng in clinics:
        key = f'{city}|{loc}'
        for cat, kw in KEYWORDS.items():
            if key in out[cat]: done += 1; continue   # resume: skip already-crawled
            items = [it for it in maps(kw, lat, lng) if it.get('type') == 'maps_search']
            comps = []; ours = None
            for it in items:
                title = it.get('title') or ''
                rec = {'name': title, 'rating': (it.get('rating') or {}).get('value'),
                       'reviews': (it.get('rating') or {}).get('votes_count'),
                       'category': it.get('category'), 'pos': it.get('rank_absolute'),
                       'place_id': it.get('place_id'), 'address': it.get('address'),
                       'domain': it.get('domain'), 'is_paid': it.get('is_paid', False)}
                ilat, ilng = it.get('latitude'), it.get('longitude')
                rec['km'] = hav(lat, lng, ilat, ilng) if (ilat and ilng) else None
                if 'allo' in title.lower() or 'allohealth' in (it.get('domain') or ''):
                    ours = rec
                else:
                    comps.append(rec)
            out[cat][key] = {'our': ours, 'competitors': comps, 'lat': lat, 'lng': lng}
            done += 1
            time.sleep(0.4)
            if done % 15 == 0:
                json.dump(out, open(outpath, 'w')); print(f'  {done}/{total} (checkpoint)', flush=True)
    json.dump(out, open(outpath, 'w'))
    tc = sum(len(v.get('competitors', [])) for cat in out.values() for v in cat.values())
    print(f'done · {len(clinics)} clinics × {len(KEYWORDS)} cats · {tc} competitor rows · data_serp_dfs.json')

if __name__ == '__main__':
    main()
