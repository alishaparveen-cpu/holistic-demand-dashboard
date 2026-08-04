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
      "gads":    [week0..weekN],   # Google Ads leads
      "bk_gads": [week0..weekN],   # bookings from Google Ads leads (bkseg != 'none')
      "gmb":     [week0..weekN],   # GMB leads (Google Maps profile)
      "bk_gmb":  [week0..weekN],   # bookings from GMB leads
    }, ...
  }
"""
import os, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def normalize(s):
    return s.lower().replace(' ', '').replace('-', '').replace('.', '').replace('_', '').replace('/', '')

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
        "note": "Per-clinic Google Ads and GMB leads + bookings from data_leads.json. "
                "gads/bk_gads = Google Ads funnel; gmb/bk_gmb = GMB (Maps) funnel. "
                "bkseg != 'none' = lead converted to an appointment (offline or online).",
        "generated_at": __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
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
            # Try partial match on loc
            partial = [lk for (lc, ll), lk in leads_by_norm.items()
                       if lc == normalize(city) and (ll in normalize(loc) or normalize(loc) in ll)]
            if partial:
                leads_key = partial[0]

        if not leads_key:
            unmatched.append(f'{rk} ({city}|{loc})')
            continue

        cells = leads_raw[leads_key].get('cells', [])
        gads    = [0]*N
        bk_gads = [0]*N
        gmb     = [0]*N
        bk_gmb  = [0]*N
        for cell in cells:
            ch    = cell.get('ch', '')
            bkseg = cell.get('bkseg', 'none')
            w_arr = cell.get('w', [])
            booked = bkseg != 'none'
            is_gads = ch == 'Google Ads'
            is_gmb  = ch in ('GMB', 'Google Maps (GMB)')
            for i in range(min(N, len(w_arr))):
                cnt = w_arr[i]
                if not cnt: continue
                if is_gads:
                    gads[i] += cnt
                    if booked: bk_gads[i] += cnt
                if is_gmb:
                    gmb[i] += cnt
                    if booked: bk_gmb[i] += cnt

        out[rk] = {"city": city, "loc": loc,
                   "gads": gads, "bk_gads": bk_gads,
                   "gmb": gmb,  "bk_gmb": bk_gmb}
        matched += 1

    json.dump(out, open(out_path, 'w'), separators=(',', ':'))
    print(f"Wrote {out_path}: {matched} clinics matched, {len(unmatched)} unmatched")
    if unmatched:
        print("Unmatched:", unmatched[:10])

if __name__ == '__main__':
    main()
