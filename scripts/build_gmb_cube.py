#!/usr/bin/env python3
"""Build data_gmb_tab.json — the cube behind the new GMB tab (gmb.html).

Assembles, per clinic "City|Locality" (+ city & national rollups), on ONE weekly axis:
  • Performance (GBP Performance API, via data_gmb_insights.json):
      impr  = SUM of the 4 BUSINESS_IMPRESSIONS_* metrics (desktop/mobile × Search/Maps).
              NB the old GBP "searches/queries" breakdown is DEPRECATED — impressions is all Google exposes.
      calls / website / directions = CALL_CLICKS / WEBSITE_CLICKS / BUSINESS_DIRECTION_REQUESTS
      interactions = calls + website + directions
      days = calendar days GBP actually reported that week (<7 → immature/trailing week)
  • Reviews (allo_health.external_reviews google/gmb, via data_reviews.json):
      n = new reviews that week ; neg = rating<=2 ; pos = n-neg ; rating = avg that week
  • Rival (data_competition.json, per category SH/STI/MH):
      our_reviews / our_rating / our_rank vs the #1 map-pack rival (name/reviews/rating) → "out-reviewing"
  • GMB leads (data_leads_city.json, channel=GMB): call vs web, mapped onto the GMB weekly axis.

rev_cat (category-tagged review velocity) is left as a stub {} — filled by a later Redshift text pull.
Pure-local (no cluster). Run: python3 scripts/build_gmb_cube.py
"""
import os, json
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def L(f):
    p = os.path.join(ROOT, f)
    return json.load(open(p)) if os.path.exists(p) else {}

INS  = L('data_gmb_insights.json')
REV  = L('data_reviews.json')
COMP = L('data_competition.json')
LEADS= L('data_leads_city.json')
RCATC= L('data_gmb_review_cat.json').get('clinics', {})   # per-clinic category-tagged review velocity

WEEKS = INS.get('_meta', {}).get('weeks') or REV.get('_meta', {}).get('weeks') or []
NW = len(WEEKS)
Z = lambda: [0]*NW
def add(a, b): return [(a[i] if i < len(a) else 0) + (b[i] if i < len(b) else 0) for i in range(NW)]

CLINICS = sorted((set(INS) | set(REV)) - {'_meta'})

# ── GMB leads (channel=GMB) mapped onto the GMB weekly axis ──
lw = LEADS.get('_meta', {}).get('weeks', [])
lidx = {w: i for i, w in enumerate(lw)}
gcall = defaultdict(Z); gwa = defaultdict(Z); gweb = defaultdict(Z)   # clinic -> weekly array on GMB axis (matches demand-view GMB medium split)
for city, node in LEADS.items():
    if city == '_meta': continue
    for c in node.get('cells', []):
        if c.get('ch') != 'GMB': continue
        loc = c.get('loc') or ''
        key = f'{city}|{loc}' if loc else None
        if not key: continue
        w = c.get('w') or []; md = c.get('md') or ''
        tgt = gcall[key] if md == 'call' else (gwa[key] if md.startswith('wa') else gweb[key])
        for gi, wk in enumerate(WEEKS):
            j = lidx.get(wk)
            if j is not None and j < len(w) and w[j]:
                tgt[gi] += w[j]

# ── rival (out-reviewing) per clinic, per category ──
rival = defaultdict(dict)   # clinic -> {cat: {...}}
for cat in ('SH', 'STI', 'MH'):
    for key, e in (COMP.get(cat, {}).get('clinics', {}) or {}).items():
        if not isinstance(e, dict): continue
        comps = [x for x in (e.get('competitors') or []) if x.get('rel') is not False] or (e.get('competitors') or [])
        top = comps[0] if comps else {}
        rival[key][cat] = dict(our_reviews=e.get('our_reviews') or 0, our_rating=e.get('our_rating'),
                               our_rank=e.get('our_rank'), top_name=top.get('name'),
                               top_reviews=top.get('reviews') or 0, top_rating=top.get('rating'))

def clinic_block(key):
    ins = INS.get(key, {}); rev = REV.get(key, {})
    n = rev.get('n', Z()); neg = rev.get('neg', Z()); rating = rev.get('rating', [None]*NW)
    pos = [max(0, (n[i] if i < len(n) else 0) - (neg[i] if i < len(neg) else 0)) for i in range(NW)]
    calls = ins.get('calls', Z()); web = ins.get('website', Z()); dirs = ins.get('directions', Z())
    return dict(
        impr=ins.get('searches', Z()), calls=calls, website=web, directions=dirs,
        interactions=[calls[i]+web[i]+dirs[i] if i < len(calls) else 0 for i in range(NW)],
        days=ins.get('days', [7]*NW),
        rev_n=[n[i] if i < len(n) else 0 for i in range(NW)], rev_pos=pos,
        rev_neg=[neg[i] if i < len(neg) else 0 for i in range(NW)],
        rev_rating=[rating[i] if i < len(rating) else None for i in range(NW)],
        rev_cat=RCATC.get(key, {}),   # category-tagged review velocity {SH/STI/MH/general: [..NW]} from pull_gmb_review_cat.py
        gmb_call=gcall.get(key, Z()), gmb_wa=gwa.get(key, Z()), gmb_web=gweb.get(key, Z()),
        rival=rival.get(key, {}))

clinics = {k: clinic_block(k) for k in CLINICS}

# ── rollups: city + national (sum the weekly arrays; rival aggregated as sum + #clinics-leading) ──
PERF = ['impr', 'calls', 'website', 'directions', 'interactions', 'rev_n', 'rev_pos', 'rev_neg', 'gmb_call', 'gmb_wa', 'gmb_web']
def roll(keys):
    out = {m: Z() for m in PERF}
    rat_num = Z(); rat_den = Z()
    riv = defaultdict(lambda: dict(our=0, top=0, lead=0, n=0))
    rcat = {c: Z() for c in ('SH', 'STI', 'MH', 'general')}
    for k in keys:
        b = clinics[k]
        for m in PERF: out[m] = add(out[m], b[m])
        for i in range(NW):
            if b['rev_rating'][i] is not None and b['rev_n'][i]:
                rat_num[i] += b['rev_rating'][i]*b['rev_n'][i]; rat_den[i] += b['rev_n'][i]
        for c in rcat:
            if b['rev_cat'].get(c): rcat[c] = add(rcat[c], b['rev_cat'][c])
        for cat, r in b['rival'].items():
            riv[cat]['our'] += r['our_reviews']; riv[cat]['top'] += r['top_reviews']
            riv[cat]['n'] += 1; riv[cat]['lead'] += 1 if r['our_reviews'] >= r['top_reviews'] else 0
    out['rev_rating'] = [round(rat_num[i]/rat_den[i], 2) if rat_den[i] else None for i in range(NW)]
    out['rev_cat'] = rcat
    out['days'] = [7]*NW
    out['rival'] = {cat: dict(our_reviews=v['our'], top_reviews=v['top'], clinics_leading=v['lead'], clinics=v['n'])
                    for cat, v in riv.items()}
    return out

cities = defaultdict(list)
for k in CLINICS: cities[k.split('|')[0]].append(k)
city_roll = {c: roll(ks) for c, ks in cities.items()}
nat_roll = roll(CLINICS)

out = {'_meta': {'weeks': WEEKS,
                 'note': "GMB tab cube. impr = total GBP impressions (BUSINESS_IMPRESSIONS_* summed; the old "
                         "searches breakdown is deprecated). interactions = calls+website+directions. reviews from "
                         "allo_health.external_reviews (google/gmb); neg = rating<=2. rival from data_competition. "
                         "rev_cat = review text keyword-tagged SH/STI/MH (general = no clinical mention, ~64%).",
                 'metrics': PERF},
       'clinics': clinics, 'cities': city_roll, 'national': nat_roll}
json.dump(out, open(os.path.join(ROOT, 'data_gmb_tab.json'), 'w'), separators=(',', ':'))
print(f'wrote data_gmb_tab.json · {len(clinics)} clinics · {len(city_roll)} cities · {NW} weeks ({WEEKS[-1]}→{WEEKS[0]})')
tot = nat_roll
print(f'national last wk: impr={tot["impr"][0]} calls={tot["calls"][0]} interactions={tot["interactions"][0]} '
      f'reviews={tot["rev_n"][0]} (neg {tot["rev_neg"][0]}) gmb_leads_call={tot["gmb_call"][0]}')
print('rival (national, our vs top-rival total reviews):', tot['rival'])
