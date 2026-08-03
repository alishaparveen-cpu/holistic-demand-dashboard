#!/usr/bin/env python3
"""Regenerate /tmp/clinic_coords.tsv (city, locality, name, lat, lng) for the MH competitor re-crawl,
from the coordinates already stored per MH clinic in data_serp_dfs.json. One row per unique MH clinic
(scoped to MH so the re-pull doesn't touch other verticals or spawn phantom rows)."""
import os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.join(ROOT, 'data_serp_dfs.json')))
seen = {}
for key, v in (d.get('MH') or {}).items():
    if '|' not in key or not isinstance(v, dict): continue
    if v.get('lat') and v.get('lng') and key not in seen:
        seen[key] = (v['lat'], v['lng'])
with open('/tmp/clinic_coords.tsv', 'w') as f:
    for key, (lat, lng) in sorted(seen.items()):
        city, loc = key.split('|', 1)
        f.write('\t'.join([city, loc, loc, str(lat), str(lng)]) + '\n')
print(f'wrote /tmp/clinic_coords.tsv · {len(seen)} MH clinics')
