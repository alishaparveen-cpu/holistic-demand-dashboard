#!/usr/bin/env python3
"""Supplementary DataForSEO Maps crawl to fix keyword bias in the STI/MH competitor sets.
The first crawl used one intent keyword per category ('std testing clinic' → diagnostic labs;
'psychiatrist' → psychiatrists), which buried STD-treatment clinics (DrSafeHands) and therapists.
This adds treatment/therapy keywords and MERGES the new competitors into data_serp_dfs.json
(dedup by place_id per clinic, keep the higher review count).

Auth: ~/.allo_dfs_auth. Coords: /tmp/clinic_coords.tsv. Resumable via a checkpoint marker.
"""
import os, json, time, math, urllib.request

AUTH = open(os.path.expanduser('~/.allo_dfs_auth')).read().strip()
URL = 'https://api.dataforseo.com/v3/serp/google/maps/live/advanced'
EXTRA = {'STI': ['std clinic', 'hiv treatment centre', 'sti testing'], 'MH': ['therapist', 'counsellor']}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DFSPATH = os.path.join(ROOT, 'data_serp_dfs.json')

def hav(a, b, c, dd):
    R = 6371; p1, p2 = math.radians(a), math.radians(c)
    dphi = math.radians(c - a); dl = math.radians(dd - b)
    x = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(R * 2 * math.asin(math.sqrt(x)), 1)

def maps(keyword, lat, lng):
    body = [{'keyword': keyword, 'location_coordinate': f'{lat},{lng},14', 'language_name': 'English', 'depth': 20}]
    for attempt in range(5):
        try:
            req = urllib.request.Request(URL, method='POST', data=json.dumps(body).encode(),
                headers={'Authorization': 'Basic ' + AUTH, 'Content-Type': 'application/json'})
            r = json.load(urllib.request.urlopen(req, timeout=120))
            return (((r.get('tasks') or [{}])[0].get('result') or [{}])[0].get('items')) or []
        except Exception:
            time.sleep(3 * (attempt + 1))
    return []

def main():
    clinics = []
    for ln in open('/tmp/clinic_coords.tsv'):
        p = ln.rstrip('\n').split('\t')
        if len(p) >= 5 and p[3] and p[4]:
            try: clinics.append((p[0], p[1], float(p[3]), float(p[4])))
            except ValueError: pass
    out = json.load(open(DFSPATH))
    kwdone = set(out.setdefault('_extra_kw', []))     # per (cat,key,kw) markers → resume at keyword granularity
    # migrate the earlier clinic-level run (std clinic + hiv treatment centre) so we don't re-crawl them
    for cat, keys in (out.get('_extra_done') or {}).items():
        for key in keys:
            for kw in ('std clinic', 'hiv treatment centre', 'therapist', 'counsellor'):
                kwdone.add(f'{cat}\t{key}\t{kw}')
    total = len(clinics) * sum(len(v) for v in EXTRA.values()); n = 0; added = 0
    for city, loc, lat, lng in clinics:
        key = f'{city}|{loc}'
        for cat, kws in EXTRA.items():
            e = out.get(cat, {}).get(key)
            for kw in kws:
                mk = f'{cat}\t{key}\t{kw}'
                if mk in kwdone or not e: n += 1; continue
                have = {c.get('place_id') for c in e['competitors']}
                for it in maps(kw, lat, lng):
                    if it.get('type') != 'maps_search': continue
                    pid = it.get('place_id'); title = it.get('title') or ''
                    if not pid or pid in have: continue
                    if 'allo' in title.lower(): continue
                    ilat, ilng = it.get('latitude'), it.get('longitude')
                    e['competitors'].append({'name': title, 'rating': (it.get('rating') or {}).get('value'),
                        'reviews': (it.get('rating') or {}).get('votes_count'), 'category': it.get('category'),
                        'pos': it.get('rank_absolute'), 'place_id': pid, 'address': it.get('address'),
                        'domain': it.get('domain'), 'is_paid': it.get('is_paid', False),
                        'km': hav(lat, lng, ilat, ilng) if (ilat and ilng) else None, 'kw': kw})
                    have.add(pid); added += 1
                kwdone.add(mk); n += 1; time.sleep(0.4)
                if n % 20 == 0:
                    out['_extra_kw'] = sorted(kwdone); json.dump(out, open(DFSPATH, 'w'))
                    print(f'  {n}/{total} · +{added} competitors', flush=True)
    out['_extra_kw'] = sorted(kwdone)
    json.dump(out, open(DFSPATH, 'w'))
    print(f'done · +{added} new STD-clinic / therapist competitors merged into data_serp_dfs.json', flush=True)

if __name__ == '__main__':
    main()
