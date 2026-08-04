#!/usr/bin/env python3
"""Build data_clinic_leads.json — per-clinic weekly leads/bookings for Campaign Compose.

Sources:
  - data_leads.json   : per-clinic leads cube (City|Locality keys, weekly arrays)
  - data_clinic_reach.json : clinic registry (locality_city keys, city/loc fields)

Output data_clinic_leads.json keyed by locality_city (same as data_clinic_reach.json):
  {
    "_meta": { "weeks": [...] },
    "indiranagar_bangalore": {
      "city": "Bangalore", "loc": "Indiranagar",
      "by_cat": {
        "all":   { "gads":[...], "bk_gads":[...], "gmb":[...], "bk_gmb":[...] },
        "SH":    { ... },
        "STI":   { ... },
        "MH":    { ... },
        "Other": { ... },   # na + unknown + Other + anything not SH/STI/MH
      }
    }, ...
  }
"""
import os, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def normalize(s):
    return s.lower().replace(' ', '').replace('-', '').replace('.', '').replace('_', '').replace('/', '')

KNOWN_CATS = ('SH', 'STI', 'MH')  # named categories; everything else → 'Other'

def empty_bucket(N):
    return {"gads": [0]*N, "bk_gads": [0]*N, "gmb": [0]*N, "bk_gmb": [0]*N}

def main():
    leads_path  = os.path.join(ROOT, 'data_leads.json')
    reach_path  = os.path.join(ROOT, 'data_clinic_reach.json')
    out_path    = os.path.join(ROOT, 'data_clinic_leads.json')

    leads_raw = json.load(open(leads_path))
    reach_raw = json.load(open(reach_path))
    leads_meta = leads_raw.get('_meta', {})
    weeks = leads_meta.get('weeks', [])
    N = len(weeks)

    # Build leads lookup: normalized (city, loc) -> leads key
    leads_by_norm = {}
    for k, v in leads_raw.items():
        if k == '_meta': continue
        parts = k.split('|')
        if len(parts) == 2:
            city, loc = parts[0], parts[1]
            leads_by_norm[(normalize(city), normalize(loc))] = k

    out = {"_meta": {
        "weeks": weeks,
        "note": "Per-clinic Google Ads and GMB leads + bookings by category. "
                "by_cat.all = all categories; by_cat.SH/STI/MH = specific; "
                "by_cat.Other = na+unknown+Other+anything not SH/STI/MH. "
                "gads/bk_gads = Google Ads; gmb/bk_gmb = GMB (Maps). "
                "bkseg != 'none' = converted to an appointment.",
        "generated_at": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    }}

    matched = 0
    unmatched = []
    for rk, rv in reach_raw.items():
        if rk == '_meta': continue
        city = rv.get('city', '')
        loc  = rv.get('loc', rv.get('locality', ''))
        lookup = (normalize(city), normalize(loc))
        leads_key = leads_by_norm.get(lookup)
        if not leads_key:
            partial = [lk for (lc, ll), lk in leads_by_norm.items()
                       if lc == normalize(city) and (ll in normalize(loc) or normalize(loc) in ll)]
            if partial:
                leads_key = partial[0]

        if not leads_key:
            unmatched.append(f'{rk} ({city}|{loc})')
            continue

        cells = leads_raw[leads_key].get('cells', [])

        # Initialize buckets: all + SH + STI + MH + Other
        buckets = {k: empty_bucket(N) for k in ['all'] + list(KNOWN_CATS) + ['Other']}

        for cell in cells:
            ch    = cell.get('ch', '')
            cat   = cell.get('cat', '')
            bkseg = cell.get('bkseg', 'none')
            w_arr = cell.get('w', [])
            booked  = bkseg != 'none'
            is_gads = ch == 'Google Ads'
            is_gmb  = ch in ('GMB', 'Google Maps (GMB)')
            if not (is_gads or is_gmb):
                continue

            # Map cat → bucket keys to add to
            bkt_keys = ['all']
            if cat in KNOWN_CATS:
                bkt_keys.append(cat)
            else:
                bkt_keys.append('Other')   # na, unknown, Other, anything else

            for i in range(min(N, len(w_arr))):
                cnt = w_arr[i]
                if not cnt: continue
                for bkt_key in bkt_keys:
                    bkt = buckets[bkt_key]
                    if is_gads:
                        bkt['gads'][i] += cnt
                        if booked: bkt['bk_gads'][i] += cnt
                    if is_gmb:
                        bkt['gmb'][i] += cnt
                        if booked: bkt['bk_gmb'][i] += cnt

        # Only store categories that have data
        by_cat = {k: bkt for k, bkt in buckets.items()
                  if any(bkt[f][i] for f in bkt for i in range(N))}
        if not by_cat:
            unmatched.append(f'{rk} (no gads/gmb leads)')
            continue

        out[rk] = {"city": city, "loc": loc, "by_cat": by_cat}
        matched += 1

    json.dump(out, open(out_path, 'w'), separators=(',', ':'))
    print(f"Wrote {out_path}: {matched} clinics matched, {len(unmatched)} unmatched")
    if unmatched:
        print("Unmatched:", unmatched[:10])

if __name__ == '__main__':
    main()
