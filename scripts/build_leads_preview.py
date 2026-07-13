#!/usr/bin/env python3
"""PREVIEW data_leads.json — attributable-leads cube (channel x medium x booked-status x week).
Real numbers where we have them offline: GMB + Google leads/booked/notbooked come from the (real, Redshift-built)
data_notbooked.json; GMB is split into call vs web using the REAL call:web ratio from the leads CSV per week.
Organic + exact per-medium booked come from the SSO run (build_notbooked.py) — this is a stand-in until then.
Schema matches build_notbooked.py's data_leads.json exactly, so the SSO run is a drop-in replacement.
"""
import os, csv, re, json, datetime
from collections import defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = '/Users/alishaparveen/Downloads/download5U71BH-ZF7a_c5e9LxecQ-0-0-v3.csv'
NB = json.load(open(os.path.join(ROOT, 'data_notbooked.json')))
WEEKS = NB['_meta']['weeks']                      # newest-first, 26 Mondays
WI = {w: i for i, w in enumerate(WEEKS)}; N = len(WEEKS)
IND_GMB_NUMS = {'8047160881', '8047281164'}       # Indiranagar GMB call numbers

def num(s): return re.sub(r'[^0-9]', '', s or '')[-10:]
def wk_monday(ts):                                # created_at + 5.5h IST -> that week's Monday (YYYY-MM-DD)
    dt = datetime.datetime.strptime(ts[:19], '%Y-%m-%d %H:%M:%S') + datetime.timedelta(hours=5, minutes=30)
    return (dt - datetime.timedelta(days=dt.weekday())).strftime('%Y-%m-%d')

# --- real call vs web GMB-Indiranagar lead counts per week, from the CSV ---
call = [0]*N; web = [0]*N
for r in csv.DictReader(open(CSV)):
    if (r.get('utm_source') or '').strip().lower() != 'gmb':
        continue
    camp = (r.get('utm_campaign') or '').lower()
    try:
        wk = wk_monday(r['created_at'])
    except Exception:
        continue
    if wk not in WI:
        continue
    i = WI[wk]
    if camp == 'inbound_call' and num(r.get('utm_medium')) in IND_GMB_NUMS:
        call[i] += 1
    elif camp == 'indiranagar-clinic-gmb':
        web[i] += 1

def split(total_arr, ratio_web):                  # split an int array into (call_part, web_part) by weekly web-ratio
    c = [0]*N; w = [0]*N
    for i in range(N):
        wv = round(total_arr[i] * ratio_web[i]); wv = max(0, min(total_arr[i], wv))
        w[i] = wv; c[i] = total_arr[i] - wv
    return c, w

ratio_web = [(web[i] / (call[i] + web[i])) if (call[i] + web[i]) else 0.0 for i in range(N)]

def cell(ch, md, bk, arr): return {'ch': ch, 'md': md, 'bk': bk, 'w': arr}

out = {'_meta': {'weeks': WEEKS, 'channels': ['GMB', 'Google', 'Organic'], 'mediums': ['call', 'web'],
                 'preview': True,
                 'note': 'PREVIEW: GMB+Google totals are real (Redshift); GMB call/web split is the real CSV ratio; '
                         'exact per-medium booked + Organic land on the SSO run of build_notbooked.py.'}}
ind = NB.get('Bangalore|Indiranagar', {})
cells = []
if 'GMB' in ind:
    for key in ('booked', 'notbooked'):
        c, w = split(ind['GMB'][key], ratio_web)
        cells.append(cell('GMB', 'call', key, c))
        cells.append(cell('GMB', 'web', key, w))
if 'Google' in ind:
    for key in ('booked', 'notbooked'):
        cells.append(cell('Google', 'call', key, ind['Google'][key]))   # Google attributed via a call
out['Bangalore|Indiranagar'] = {'cells': cells}

json.dump(out, open(os.path.join(ROOT, 'data_leads.json'), 'w'), separators=(',', ':'))
tot = sum(sum(c['w']) for c in cells)
bk = sum(sum(c['w']) for c in cells if c['bk'] == 'booked')
print(f'wrote PREVIEW data_leads.json · Indiranagar {tot} leads · {bk} booked · {tot-bk} not booked')
for ch in ('GMB', 'Google'):
    for md in ('call', 'web'):
        got = [c for c in cells if c['ch'] == ch and c['md'] == md]
        if got:
            L = sum(sum(c['w']) for c in got); B = sum(sum(c['w']) for c in got if c['bk'] == 'booked')
            print(f'  {ch:7} {md:4}: {L:4} leads · {B:3} booked · {L-B:3} not booked')
