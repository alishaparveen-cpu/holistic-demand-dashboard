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

def monday(dstr):
    d = datetime.date.fromisoformat(dstr)
    return (d - datetime.timedelta(days=d.weekday())).isoformat()

ga = json.load(open(DAILY))
# accumulate per (dim,key,week) metrics
acc = defaultdict(lambda: defaultdict(lambda: {'impr':0,'clicks':0,'cost':0.0,'conv':0.0,'leads':0,'booked':0}))
weeks = set()

# clicks/impr/cost/conv from GA daily
for cm in ga['campaigns']:
    city, prod = cm['city'], cm['product']
    for i, day in enumerate(ga['days']):
        wk = monday(day); weeks.add(wk)
        for dimkey in (('city',city),('product',prod),('total','All')):
            a = acc[dimkey][wk]
            a['impr'] += cm['impr'][i]; a['clicks'] += cm['clicks'][i]
            a['cost'] += cm['cost'][i]; a['conv'] += cm['conv'][i]

# leads/booked from the gclid TSV (tag via campaign name)
for line in open(LEADS_TSV):
    p = line.rstrip('\n').split('\t')
    if len(p) < 4: continue
    wk, camp, leads, booked = p[0], p[1], int(p[2]), int(p[3])
    weeks.add(wk)
    city, prod = parse_name(camp)
    for dimkey in (('city',city),('product',prod),('total','All')):
        a = acc[dimkey][wk]
        a['leads'] += leads; a['booked'] += booked

weeks = [w for w in sorted(weeks) if w < '2026-06-15']   # drop the current incomplete week (Jun 8+)
def series(dimkey):
    out = {k:[0]*len(weeks) for k in ('impr','clicks','cost','conv','leads','booked')}
    for wi, wk in enumerate(weeks):
        m = acc[dimkey].get(wk)
        if not m: continue
        for k in out: out[k][wi] = round(m[k],2) if k=='cost' else (round(m[k]) if k=='conv' else m[k])
    return out

dims = {'city':{}, 'product':{}, 'total':{}}
for (dim,key) in acc:
    dims[dim][key] = series((dim,key))

res = {'_meta':{'source':'GA daily clicks (data_ga_daily.json) + Redshift gclid leads→bookings (fetch_ga_leads.sql)',
        'pulled':ga['_meta'].get('pulled'),
        'note':'Weekly. clicks/impr/cost/conv = Google Ads (campaign-tagged). leads = unique gclid-lead phones, booked = matched to an SC appt within 14d. Tagged to city/category from the campaign name, so clicks↔leads align. National/Online = non-local campaigns (no city).'},
    'weeks':weeks, 'dims':dims}
json.dump(res, open(OUT,'w'), separators=(',',':'))
tot = dims['total'].get('All',{})
print(f"wrote {OUT} · {len(weeks)} weeks · cities {len(dims['city'])} · products {sorted(dims['product'])}")
if tot: print(f"  latest wk: clicks {tot['clicks'][-1]} leads {tot['leads'][-1]} booked {tot['booked'][-1]}")
