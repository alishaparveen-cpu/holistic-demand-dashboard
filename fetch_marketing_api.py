#!/usr/bin/env python3
"""
fetch_marketing_api.py — pulls live marketing-platform data the booking pipeline
can't see, and writes data_marketing.json for the dashboard.

  1. Google Ads (account 3190189170 "Allo Health - ...Sexologists"):
     weekly Search Impression Share, budget-lost IS, rank-lost IS, impressions,
     clicks, cost.  ← the "are we capturing available paid demand?" signal.
  2. Google Business Profile (account 104278284314268556784, 67 verified
     clinic locations): weekly impressions split Search vs Maps × Desktop vs
     Mobile, plus actions (calls / website / directions / conversations).
     ← the organic brand-discovery signal that GMB bookings ride on.

Secrets are read from /tmp/allo_secrets.json (chmod 600, OUTSIDE the repo,
git-ignored).  NOTHING secret is written into the output file.

Weeks are keyed by Monday (YYYY-MM-DD) to align with the dashboard week keys.
"""
import json, sys, datetime as dt
from collections import defaultdict
import requests

SECRETS = '/tmp/allo_secrets.json'
OUT     = 'data_marketing.json'
GADS_VER = 'v21'
GADS_ACCOUNT = '3190189170'                     # live paid Search account
GBP_ACCOUNT  = 'accounts/104278284314268556784' # 67 verified clinic locations
WEEKS_BACK   = 10

def load_secrets():
    try:
        return json.load(open(SECRETS))
    except FileNotFoundError:
        sys.exit(f'ERROR: {SECRETS} not found. This script needs live OAuth creds.')

def access_token(block):
    r = requests.post('https://oauth2.googleapis.com/token', data={
        'client_id': block['client_id'], 'client_secret': block['client_secret'],
        'refresh_token': block['refresh_token'], 'grant_type': 'refresh_token'}, timeout=30)
    r.raise_for_status()
    return r.json()['access_token']

def monday(d):
    return d - dt.timedelta(days=d.weekday())

# ── window ────────────────────────────────────────────────────────────────────
today      = dt.date.today()
last_sun   = today - dt.timedelta(days=today.weekday() + 1)   # most recent Sunday
last_mon   = monday(last_sun)                                  # Monday of that week
start_mon  = last_mon - dt.timedelta(weeks=WEEKS_BACK - 1)
end_day    = last_sun
print(f'window: {start_mon} .. {end_day}  ({WEEKS_BACK} weeks)')

# ── 1. Google Ads ─────────────────────────────────────────────────────────────
def fetch_google_ads(sec):
    tok = access_token(sec['google_ads'])
    q = f"""
      SELECT segments.week, metrics.impressions, metrics.clicks, metrics.cost_micros,
             metrics.search_impression_share,
             metrics.search_budget_lost_impression_share,
             metrics.search_rank_lost_impression_share
      FROM customer
      WHERE segments.date BETWEEN '{start_mon}' AND '{end_day}'
      ORDER BY segments.week """
    r = requests.post(
        f'https://googleads.googleapis.com/{GADS_VER}/customers/{GADS_ACCOUNT}/googleAds:search',
        headers={'Authorization': f'Bearer {tok}',
                 'developer-token': sec['google_ads']['developer_token']},
        json={'query': q}, timeout=60)
    r.raise_for_status()
    weeks = {}
    for row in r.json().get('results', []):
        m = row['metrics']
        weeks[row['segments']['week']] = {
            'impressions':    int(m.get('impressions', 0)),
            'clicks':         int(m.get('clicks', 0)),
            'cost':           round(int(m.get('costMicros', 0)) / 1e6),
            'search_is':      round(float(m.get('searchImpressionShare', 0)), 4),
            'budget_lost_is': round(float(m.get('searchBudgetLostImpressionShare', 0)), 4),
            'rank_lost_is':   round(float(m.get('searchRankLostImpressionShare', 0)), 4),
        }
    return {'account': GADS_ACCOUNT, 'weeks': weeks}

# ── 2. Google Business Profile ────────────────────────────────────────────────
GBP_METRICS = ['BUSINESS_IMPRESSIONS_DESKTOP_SEARCH', 'BUSINESS_IMPRESSIONS_MOBILE_SEARCH',
               'BUSINESS_IMPRESSIONS_DESKTOP_MAPS',   'BUSINESS_IMPRESSIONS_MOBILE_MAPS',
               'CALL_CLICKS', 'WEBSITE_CLICKS', 'BUSINESS_DIRECTION_REQUESTS',
               'BUSINESS_CONVERSATIONS']
METRIC_KEY = {
    'BUSINESS_IMPRESSIONS_DESKTOP_SEARCH': 'search_desktop',
    'BUSINESS_IMPRESSIONS_MOBILE_SEARCH':  'search_mobile',
    'BUSINESS_IMPRESSIONS_DESKTOP_MAPS':   'maps_desktop',
    'BUSINESS_IMPRESSIONS_MOBILE_MAPS':    'maps_mobile',
    'CALL_CLICKS': 'calls', 'WEBSITE_CLICKS': 'website',
    'BUSINESS_DIRECTION_REQUESTS': 'directions', 'BUSINESS_CONVERSATIONS': 'conversations',
}

def fetch_gbp(sec):
    tok = access_token(sec['gbp'])
    H = {'Authorization': f'Bearer {tok}'}
    # list locations
    locs, pt = [], ''
    while True:
        u = (f'https://mybusinessbusinessinformation.googleapis.com/v1/{GBP_ACCOUNT}/locations'
             f'?readMask=name,title,storefrontAddress&pageSize=100')
        if pt: u += f'&pageToken={pt}'
        j = requests.get(u, headers=H, timeout=30).json()
        locs += j.get('locations', [])
        pt = j.get('nextPageToken')
        if not pt: break
    print(f'GBP locations: {len(locs)}')

    wk = defaultdict(lambda: defaultdict(int))     # week(Mon) -> metric -> sum
    wkcity = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))  # week -> city -> metric
    params_base = [
        ('dailyRange.start_date.year', start_mon.year), ('dailyRange.start_date.month', start_mon.month),
        ('dailyRange.start_date.day', start_mon.day),
        ('dailyRange.end_date.year', end_day.year), ('dailyRange.end_date.month', end_day.month),
        ('dailyRange.end_date.day', end_day.day),
    ] + [('dailyMetrics', m) for m in GBP_METRICS]

    for i, loc in enumerate(locs):
        locid = loc['name'].split('/')[-1]
        city  = loc.get('storefrontAddress', {}).get('locality', '?')
        u = f'https://businessprofileperformance.googleapis.com/v1/locations/{locid}:fetchMultiDailyMetricsTimeSeries'
        r = requests.get(u, headers=H, params=params_base, timeout=60)
        if r.status_code != 200:
            print(f'  [{i+1}/{len(locs)}] {locid} HTTP {r.status_code} (skip)')
            continue
        for series in r.json().get('multiDailyMetricTimeSeries', []):
            for dm in series.get('dailyMetricTimeSeries', []):
                key = METRIC_KEY.get(dm['dailyMetric'])
                if not key: continue
                for dv in dm.get('timeSeries', {}).get('datedValues', []):
                    v = int(dv.get('value', 0) or 0)
                    if not v: continue
                    d = dv['date']
                    wm = monday(dt.date(d['year'], d['month'], d['day'])).isoformat()
                    wk[wm][key] += v
                    wkcity[wm][city][key] += v
    # finalize derived totals
    weeks = {}
    for wm, mm in sorted(wk.items()):
        search = mm['search_desktop'] + mm['search_mobile']
        maps_  = mm['maps_desktop'] + mm['maps_mobile']
        weeks[wm] = dict(mm)
        weeks[wm]['search_total'] = search
        weeks[wm]['maps_total']   = maps_
        weeks[wm]['impressions_total'] = search + maps_
        weeks[wm]['actions_total'] = mm['calls'] + mm['website'] + mm['directions'] + mm['conversations']
    citywk = {wm: {c: dict(mc) for c, mc in cm.items()} for wm, cm in wkcity.items()}
    return {'locations': len(locs), 'weeks': weeks, 'by_city': citywk}

def main():
    sec = load_secrets()
    out = {'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
           'window': {'start': start_mon.isoformat(), 'end': end_day.isoformat()}}
    print('\n--- Google Ads ---')
    out['google_ads'] = fetch_google_ads(sec)
    for w, d in out['google_ads']['weeks'].items():
        print(f"  {w}  IS {d['search_is']*100:4.1f}%  budgetLost {d['budget_lost_is']*100:4.1f}%  "
              f"rankLost {d['rank_lost_is']*100:4.1f}%  cost ₹{d['cost']:,}")
    print('\n--- Google Business Profile ---')
    out['gbp'] = fetch_gbp(sec)
    for w, d in out['gbp']['weeks'].items():
        print(f"  {w}  impr {d['impressions_total']:>7,}  (search {d['search_total']:>6,} / "
              f"maps {d['maps_total']:>6,})  actions {d['actions_total']:>5,}")
    json.dump(out, open(OUT, 'w'), indent=2)
    print(f'\nwrote {OUT}')

if __name__ == '__main__':
    main()
