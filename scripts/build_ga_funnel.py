#!/usr/bin/env python3
"""Combine GA daily clicks (data_ga_daily.json) + gclid leads/bookings (/tmp/ga_leads.tsv) into a
single weekly funnel dataset keyed by CITY and by CATEGORY → data_ga_funnel2.json.

The marketing UI slices this by any week-range and compares city-vs-city or SH-vs-MH:
  clicks → leads → bookings, all consistently tagged from the campaign name.
"""
import os, json, re, datetime
from collections import defaultdict

HERE = os.path.dirname(__file__)
DAILY = os.path.join(HERE, "..", "data_ga_daily.json")
LEADS_TSV = "/tmp/ga_leads.tsv"
OUT = os.path.join(HERE, "..", "data_ga_funnel2.json")

def parse_name(name):
    m = re.match(r'T[12]_([A-Za-z]+(?:_[A-Za-z]+)*?)_(?:SH|STD|MH|ED|PE)_', name)
    city = m.group(1).replace('_',' ') if m else 'National / Online'
    u = name.upper()
    if re.search(r'(^|_)MH(_|$)', u) or 'MENTAL' in u: prod='MH'
    elif re.search(r'(^|_)STD(_|$)', u): prod='STD'
    elif re.search(r'(^|_)ED(_|$)', u): prod='ED'
    elif re.search(r'(^|_)PE(_|$)', u): prod='PE'
    elif 'BRAND' in u: prod='Brand'
    elif re.search(r'(^|_)SH(_|$)', u): prod='SH'
    else: prod='Other'
    return (city, prod)

def parse_format(name):
    """Match-type / campaign format from the name: Exact Local, Phrase Local, Exact, Phrase, Brand, High Intent, Other."""
    u = name.upper()
    local = 'LOCAL' in u
    if 'PHRASE' in u: return 'Phrase Local' if local else 'Phrase'
    if 'EXACT'  in u: return 'Exact Local'  if local else 'Exact'
    if 'BRAND'  in u: return 'Brand'
    if 'HIGHINTENT' in u or re.search(r'(^|_)HI(_|$)', u): return 'High Intent'
    return 'Other'

def monday(dstr):
    d = datetime.date.fromisoformat(dstr)
    return (d - datetime.timedelta(days=d.weekday())).isoformat()

ga = json.load(open(DAILY))
FIELDS = ('impr','clicks','locclicks','cost','conv','leads','booked','done')
# accumulate per (dim,key,week) metrics
acc = defaultdict(lambda: defaultdict(lambda: {k:(0.0 if k=='cost' else 0) for k in FIELDS}))
weeks = set()

def dimkeys(city, prod, fmt):
    return (('city',city),('product',prod),('citycat',city+'|'+prod),('total','All'),
            ('fmt',fmt),('cityfmt',city+'|'+fmt),('catfmt',prod+'|'+fmt))

# clicks/impr/locclicks/cost/conv from GA daily
for cm in ga['campaigns']:
    city, prod, fmt = cm['city'], cm['product'], parse_format(cm.get('full',''))
    lcl = cm.get('locclicks') or [0]*len(ga['days'])
    for i, day in enumerate(ga['days']):
        wk = monday(day); weeks.add(wk)
        for dimkey in dimkeys(city, prod, fmt):
            a = acc[dimkey][wk]
            a['impr'] += cm['impr'][i]; a['clicks'] += cm['clicks'][i]; a['locclicks'] += lcl[i]
            a['cost'] += cm['cost'][i]; a['conv'] += cm['conv'][i]

# leads/booked from the gclid TSV (tag via campaign name)
for line in open(LEADS_TSV):
    p = line.rstrip('\n').split('\t')
    if len(p) < 4: continue
    wk, camp, leads, booked = p[0], p[1], int(p[2]), int(p[3])
    done = int(p[4]) if len(p) > 4 else 0
    weeks.add(wk)
    city, prod = parse_name(camp); fmt = parse_format(camp)
    for dimkey in dimkeys(city, prod, fmt):
        a = acc[dimkey][wk]
        a['leads'] += leads; a['booked'] += booked; a['done'] += done

weeks = [w for w in sorted(weeks) if w < '2026-06-22']   # drop the current incomplete week (Jun 8+)
def series(dimkey):
    out = {k:[0]*len(weeks) for k in FIELDS}
    for wi, wk in enumerate(weeks):
        m = acc[dimkey].get(wk)
        if not m: continue
        for k in out: out[k][wi] = round(m[k],2) if k=='cost' else (round(m[k]) if k=='conv' else m[k])
    return out

dims = {'city':{}, 'product':{}, 'citycat':{}, 'total':{}, 'fmt':{}, 'cityfmt':{}, 'catfmt':{}}
for (dim,key) in acc:
    dims[dim][key] = series((dim,key))

res = {'_meta':{'source':'GA daily clicks (data_ga_daily.json) + Redshift gclid leads→bookings (fetch_ga_leads.sql)',
        'pulled':ga['_meta'].get('pulled'),
        'note':'Weekly. clicks/impr/locclicks/cost/conv = Google Ads (campaign-tagged). locclicks = location-asset taps (CALLS/GET_DIRECTIONS/LOCATION_EXPANSION/LOCATION_FORMAT_CALL_TRACKING); CTR = clicks/impr. leads = unique gclid-lead phones, booked = matched to an SC appt within 14d. Dims: city, product(category), citycat, total, fmt(match-type: Exact Local/Phrase Local/Exact/Phrase/Brand/High Intent), cityfmt, catfmt. National/Online = non-local campaigns (no city).'},
    'weeks':weeks, 'dims':dims}
json.dump(res, open(OUT,'w'), separators=(',',':'))
tot = dims['total'].get('All',{})
print(f"wrote {OUT} · {len(weeks)} weeks · cities {len(dims['city'])} · products {sorted(dims['product'])}")
if tot: print(f"  latest wk: clicks {tot['clicks'][-1]} leads {tot['leads'][-1]} booked {tot['booked'][-1]}")
