#!/usr/bin/env python3
"""Regenerate data_gmb_number_clinic.json from the LIVE allo_health.locations table.

Replaces the hand-maintained JSON. Business intent (2026-07-16, Alisha):
- `allo_health.locations` (phone_no + locality + city) is the authoritative, always-current
  GMB exophone -> clinic map — covers ~96% of numbers our hand-list was missing.
- POOLED numbers (one exophone mapped to >1 clinic — e.g. 8071175797 shared across
  Vashi/Gurugram/Kilpauk, or numbers competitors reset to a common line) are EXCLUDED
  from the number->city map so those calls fall through to the AI/source_url city signal,
  which is correct for shared/sabotaged lines (a Navi Mumbai caller on a shared number
  should stay Navi Mumbai, not get pinned to whichever clinic the config names).
Run: AWS_PROFILE=redshift-data python3 scripts/refresh_gmb_map_from_locations.py
"""
import os, sys, json, subprocess, shutil, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, 'scripts', 'redshift_query.py')
OUT = os.path.join(ROOT, 'data_gmb_number_clinic.json')

# locations.city -> canonical city used across the dashboard
CITYNORM = {'MUMBAI': 'Mumbai', 'BANGALORE': 'Bangalore', 'BENGALURU': 'Bangalore',
            'Bengaluru': 'Bangalore', 'Hubballi': 'Hubli', 'Mangalore': 'Mangaluru',
            'Mysore': 'Mysuru', 'Vizag': 'Visakhapatnam'}
def norm_city(c):
    c = (c or '').strip()
    if c in CITYNORM: return CITYNORM[c]
    return c.title() if c.isupper() else c

SQL = """
SELECT RIGHT(REGEXP_REPLACE(phone_no,'[^0-9]',''),10) AS num, city, locality
FROM allo_health.locations
WHERE deleted_at IS NULL AND phone_no IS NOT NULL AND phone_no <> ''
  AND LENGTH(RIGHT(REGEXP_REPLACE(phone_no,'[^0-9]',''),10)) = 10;
"""

def main():
    p = subprocess.run([sys.executable, RQ], input=SQL, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit('query failed: ' + p.stderr[-400:])
    # group by number: collect the set of CITIES + a representative locality
    by_num = {}
    for line in p.stdout.strip().splitlines():
        c = line.split('\t')
        if len(c) < 3:
            continue
        num, city, loc = c[0], norm_city(c[1]), c[2]
        if not num or not city:
            continue
        d = by_num.setdefault(num, {'cities': set(), 'loc': loc})
        d['cities'].add(city)
    single, pooled = {}, {}
    for num, d in by_num.items():
        if len(d['cities']) > 1:           # spans MULTIPLE cities -> shared/pooled: exclude (fall to AI/URL)
            pooled[num] = d['cities']
            continue
        city = next(iter(d['cities']))     # single city (locality may vary, but city is unambiguous)
        single[num] = f"{city}|{d['loc']}"
    # back up the old hand-maintained map, then write the locations-sourced one
    if os.path.exists(OUT):
        shutil.copy(OUT, OUT + '.bak_' + datetime.date.today().isoformat())
    json.dump(single, open(OUT, 'w'), ensure_ascii=False, indent=0, separators=(',', ':'))
    print(f'wrote {OUT} · {len(single)} single-clinic numbers')
    print(f'  EXCLUDED {len(pooled)} pooled/shared numbers (fall through to AI/URL): '
          + ', '.join(f'{k}({",".join(sorted(v))})' for k, v in list(pooled.items())[:6]))

if __name__ == '__main__':
    main()
