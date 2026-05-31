#!/usr/bin/env python3
"""
fetch_gmb.py  —  Pull GMB Insights into data_gmb.json for the Allo Health dashboard.

Metrics fetched (per location, weekly):
  • QUERIES_DIRECT    — searches using business name / address  (brand recall)
  • QUERIES_INDIRECT  — category / keyword searches             (discovery demand)
  • QUERIES_CHAIN     — branded chain searches                  (brand awareness)
  • ACTIONS_DRIVING_DIRECTIONS — direction requests             (foot-traffic intent)
  • ACTIONS_PHONE     — GMB phone-call taps                     (lead proxy)

Usage:
  cd /Users/alishaparveen/holistic-demand-dashboard
  python3 scripts/fetch_gmb.py

First run: detects credentials type, opens browser for OAuth consent if needed,
           saves token.json for future headless runs.

Output: data_gmb.json in the project root (read by overview.html + diagnostic.html).
"""

import json, os, sys, datetime, re
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent.parent
CREDS_FILE = ROOT / 'credentials.json'
TOKEN_FILE = ROOT / 'token.json'
OUTPUT     = ROOT / 'data_gmb.json'

# ── Week keys matching data.json (Monday ISO dates, newest first) ──────────────
WEEK_KEYS = [
    '2026-05-18', '2026-05-11', '2026-05-04',
    '2026-04-27', '2026-04-20', '2026-04-13', '2026-04-06',
]
N_WEEKS = len(WEEK_KEYS)

# ── OAuth scopes needed ────────────────────────────────────────────────────────
SCOPES = ['https://www.googleapis.com/auth/business.manage']

# ── City alias map: GMB location display name → dashboard city key ─────────────
# Add any clinic names that don't contain the city name directly.
CITY_ALIASES = {
    'bangalore': 'Bangalore', 'bengaluru': 'Bangalore', 'blr': 'Bangalore',
    'mumbai':    'Mumbai',    'bombay':    'Mumbai',
    'pune':      'Pune',
    'hyderabad': 'Hyderabad', 'hyd':       'Hyderabad', 'secunderabad': 'Hyderabad',
    'chennai':   'Chennai',   'madras':    'Chennai',
    'navi mumbai': 'Navi Mumbai',
    'coimbatore': 'Coimbatore', 'cbe': 'Coimbatore',
    'nagpur':    'Nagpur',
    'ranchi':    'Ranchi',
    'jaipur':    'Jaipur',
    'ahmedabad': 'Ahmedabad',
    'surat':     'Surat',
    'nashik':    'Nashik',
    'aurangabad': 'Aurangabad',
    'hubli':     'Hubli',
    'mysuru':    'Mysuru',    'mysore': 'Mysuru',
    'mangaluru': 'Mangaluru', 'mangalore': 'Mangaluru',
    'bhopal':    'Bhopal',
    'visakhapatnam': 'Visakhapatnam', 'vizag': 'Visakhapatnam',
    'thane':     'Thane',
    'gandhinagar': 'Gandhinagar',
    'vijayawada': 'Vijayawada',
}

def city_from_name(display_name: str) -> str:
    n = display_name.lower()
    for alias, city in CITY_ALIASES.items():
        if alias in n:
            return city
    return 'Other'

# ── GMB API metric names → dashboard JSON keys ─────────────────────────────────
METRIC_MAP = {
    'QUERIES_DIRECT':             'queries_direct',
    'QUERIES_INDIRECT':           'queries_indirect',
    'QUERIES_CHAIN':              'queries_chain',
    'ACTIONS_DRIVING_DIRECTIONS': 'directions',
    'ACTIONS_PHONE':              'calls',
}

def zero_series():
    return [None] * N_WEEKS

def add_series(a, b):
    return [(a[i] or 0) + (b[i] or 0) for i in range(N_WEEKS)]

# ── Week alignment helpers ─────────────────────────────────────────────────────
def monday_of(dt: datetime.date) -> str:
    """Return 'YYYY-MM-DD' of the Monday that starts the week containing dt."""
    off = dt.weekday()  # 0 = Monday
    return (dt - datetime.timedelta(days=off)).isoformat()

def parse_iso_date(s: str):
    try:
        return datetime.date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None

# ── Credentials ────────────────────────────────────────────────────────────────
def get_credentials():
    from google.oauth2 import service_account
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    import google.oauth2.credentials

    if not CREDS_FILE.exists():
        sys.exit(
            f'\n✗  credentials.json not found at:\n   {CREDS_FILE}\n\n'
            '   Drop your Google Cloud credentials file there and re-run.\n'
            '   Accepted types: OAuth2 Desktop client JSON  OR  Service Account key JSON.\n'
        )

    with open(CREDS_FILE) as f:
        cdata = json.load(f)

    # ── Service account ────────────────────────────────────────────────────────
    if cdata.get('type') == 'service_account':
        print('ℹ  Service account credentials detected.')
        print('⚠  Note: GMB Insights API requires user-level OAuth in most setups.')
        print('   Attempting service-account auth — if you get 403, use an OAuth2 Desktop client JSON.')
        return service_account.Credentials.from_service_account_file(
            str(CREDS_FILE), scopes=SCOPES)

    # ── OAuth2 installed / desktop app ─────────────────────────────────────────
    print('ℹ  OAuth2 client credentials detected.')
    creds = None

    if TOKEN_FILE.exists():
        print(f'ℹ  Loading saved token from {TOKEN_FILE}')
        with open(TOKEN_FILE) as f:
            t = json.load(f)
        creds = google.oauth2.credentials.Credentials(
            token=t.get('token'),
            refresh_token=t.get('refresh_token'),
            token_uri=t.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=t.get('client_id'),
            client_secret=t.get('client_secret'),
            scopes=SCOPES,
        )

    if not creds or not creds.valid:
        # If we have a refresh_token (even when token=None), try to refresh first
        # before falling back to the browser flow.
        if creds and creds.refresh_token:
            try:
                creds.refresh(Request())
                print('ℹ  Token refreshed via refresh_token.')
            except Exception as e:
                print(f'⚠  Token refresh failed: {e}')
                print('\n🌐  Opening browser for Google auth consent...')
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
                creds = flow.run_local_server(port=0, prompt='consent')
                print('\n✓  Auth complete.')
        else:
            print('\n🌐  Opening browser for Google auth consent...')
            print('    (If no browser opens, check that port 0 is available.)\n')
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
            creds = flow.run_local_server(port=0, prompt='consent')
            print('\n✓  Auth complete.')

        with open(TOKEN_FILE, 'w') as f:
            json.dump({
                'token':         creds.token,
                'refresh_token': creds.refresh_token,
                'token_uri':     creds.token_uri,
                'client_id':     creds.client_id,
                'client_secret': creds.client_secret,
            }, f, indent=2)
        print(f'✓  Token saved → {TOKEN_FILE}  (reused on future runs)')

    return creds

# ── New Business Profile API base URLs (v4 mybusiness is fully deprecated) ─────
ACCT_API = 'https://mybusinessaccountmanagement.googleapis.com/v1'
INFO_API = 'https://mybusinessbusinessinformation.googleapis.com/v1'
PERF_API = 'https://businessprofileperformance.googleapis.com/v1'

# New Performance API metric names → dashboard JSON keys
PERF_METRICS = {
    'CALL_CLICKS':                  'calls',
    'BUSINESS_DIRECTION_REQUESTS':  'directions',
    'BUSINESS_IMPRESSIONS_DESKTOP_SEARCH': 'impressions_desktop_search',
    'BUSINESS_IMPRESSIONS_MOBILE_SEARCH':  'impressions_mobile_search',
    'BUSINESS_IMPRESSIONS_DESKTOP_MAPS':   'impressions_desktop_maps',
    'BUSINESS_IMPRESSIONS_MOBILE_MAPS':    'impressions_mobile_maps',
}
# Derived totals built after fetch
# queries_indirect / queries_direct / queries_chain come from keyword impressions

# ── API helpers ────────────────────────────────────────────────────────────────
def api_get(session, url, params=None):
    r = session.get(url, params=params)
    if not r.ok:
        raise Exception(f'{r.status_code} {r.reason} — {r.text[:200]}')
    return r.json()

# ── List GBP accounts ──────────────────────────────────────────────────────────
def list_accounts(session):
    data = api_get(session, f'{ACCT_API}/accounts')
    return data.get('accounts', [])

# ── List all locations under an account ───────────────────────────────────────
def list_locations(session, account_name):
    """
    Returns list of location objects with at minimum 'name' and 'title'.
    account_name format: 'accounts/XXXXXXXXX'
    location name format: 'locations/XXXXXXXXX'
    """
    locs, page_token = [], None
    while True:
        params = {
            'pageSize':  100,
            'readMask':  'name,title,storefrontAddress,websiteUri',
        }
        if page_token:
            params['pageToken'] = page_token
        data = api_get(session, f'{INFO_API}/{account_name}/locations', params=params)
        locs.extend(data.get('locations', []))
        page_token = data.get('nextPageToken')
        if not page_token:
            break
    return locs

# ── Fetch daily metrics for a single location ─────────────────────────────────
def fetch_daily_metric(session, loc_name, metric):
    """
    Returns { 'YYYY-MM-DD': int, ... } for daily values over the past 10 weeks.
    loc_name format: 'locations/XXXXXXXXX'
    """
    end_dt   = datetime.date.today()
    start_dt = end_dt - datetime.timedelta(weeks=11)
    params = {
        'dailyMetric': metric,
        'dailyRange.startDate.year':  start_dt.year,
        'dailyRange.startDate.month': start_dt.month,
        'dailyRange.startDate.day':   start_dt.day,
        'dailyRange.endDate.year':    end_dt.year,
        'dailyRange.endDate.month':   end_dt.month,
        'dailyRange.endDate.day':     end_dt.day,
    }
    try:
        resp = api_get(session, f'{PERF_API}/{loc_name}:getDailyMetricsTimeSeries', params=params)
    except Exception as e:
        return {}
    daily = {}
    for entry in resp.get('timeSeries', {}).get('datedValues', []):
        date_obj = entry.get('date', {})
        y, m, d = date_obj.get('year'), date_obj.get('month'), date_obj.get('day')
        if y and m and d:
            dt = datetime.date(y, m, d)
            try:
                daily[dt.isoformat()] = int(entry.get('value', 0) or 0)
            except (ValueError, TypeError):
                pass
    return daily

def daily_to_weekly(daily_dict):
    """Aggregate daily {YYYY-MM-DD: int} into {monday-YYYY-MM-DD: int} then align to WEEK_KEYS."""
    weekly = {}
    for date_str, val in daily_dict.items():
        dt = parse_iso_date(date_str)
        if not dt: continue
        wk = monday_of(dt)
        weekly[wk] = weekly.get(wk, 0) + (val or 0)
    return [weekly.get(wk) for wk in WEEK_KEYS]

# ── Fetch keyword impressions and classify discovery vs direct ─────────────────
def fetch_search_keywords(session, loc_name):
    """
    Returns { 'YYYY-MM-DD': {'discovery': int, 'direct': int} } classified by
    whether the keyword is branded ('allo') or generic.
    """
    end_dt   = datetime.date.today()
    start_dt = end_dt - datetime.timedelta(weeks=11)
    params = {
        'dailyRange.startDate.year':  start_dt.year,
        'dailyRange.startDate.month': start_dt.month,
        'dailyRange.startDate.day':   start_dt.day,
        'dailyRange.endDate.year':    end_dt.year,
        'dailyRange.endDate.month':   end_dt.month,
        'dailyRange.endDate.day':     end_dt.day,
    }
    try:
        resp = api_get(session,
            f'{PERF_API}/{loc_name}/searchkeywordimpressions:fetchMultiDailyMetricsTimeSeries',
            params=params)
    except Exception as e:
        return {}

    # resp = { 'multiDailyMetricTimeSeries': [ { 'searchKeyword': '...', 'dailyMetricTimeSeries': [...] } ] }
    disc_daily, dir_daily = {}, {}
    for kw_entry in resp.get('multiDailyMetricTimeSeries', []):
        kw     = (kw_entry.get('searchKeyword') or '').lower()
        is_dir = 'allo' in kw   # branded keyword → direct intent

        for series in kw_entry.get('dailyMetricTimeSeries', []):
            for dv in series.get('timeSeries', {}).get('datedValues', []):
                date_obj = dv.get('date', {})
                y, m, d = date_obj.get('year'), date_obj.get('month'), date_obj.get('day')
                if not (y and m and d): continue
                key = datetime.date(y, m, d).isoformat()
                val = int(dv.get('value', 0) or 0)
                if is_dir:
                    dir_daily[key]  = dir_daily.get(key, 0)  + val
                else:
                    disc_daily[key] = disc_daily.get(key, 0) + val

    return {
        'queries_direct':   daily_to_weekly(dir_daily),
        'queries_indirect': daily_to_weekly(disc_daily),
        'queries_chain':    [None] * N_WEEKS,  # chain not distinguishable via keywords
    }

# ── Fetch all metrics for one location ────────────────────────────────────────
def fetch_location_all(session, loc):
    """
    Returns { dash_key → [weekly_values] } for all metrics.
    loc: dict with 'name' (locations/XXX) and 'title'.
    """
    loc_name = loc['name']
    result   = {}

    # Performance metrics (one call per metric)
    for api_key, dash_key in PERF_METRICS.items():
        daily  = fetch_daily_metric(session, loc_name, api_key)
        result[dash_key] = daily_to_weekly(daily)

    # Derived: total search impressions
    search = [
        (result.get('impressions_desktop_search') or [None]*N_WEEKS),
        (result.get('impressions_mobile_search')  or [None]*N_WEEKS),
    ]
    result['impressions_search'] = [
        (a or 0) + (b or 0) for a, b in zip(*search)
    ]
    result['impressions_maps'] = [
        ((result.get('impressions_desktop_maps') or [None]*N_WEEKS)[i] or 0) +
        ((result.get('impressions_mobile_maps')  or [None]*N_WEEKS)[i] or 0)
        for i in range(N_WEEKS)
    ]

    # Keyword impressions → discovery / direct split
    kw = fetch_search_keywords(session, loc_name)
    result.update(kw)

    return result

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    import requests
    from google.auth.transport.requests import Request as AuthRequest

    print('\n── Allo Health  GMB Insights Fetch ──────────────────────────────')

    creds = get_credentials()

    # Create an authenticated requests.Session
    from google.auth.transport.requests import AuthorizedSession
    session = AuthorizedSession(creds)

    # ── Discover accounts ──────────────────────────────────────────────────────
    print('\n● Listing GMB accounts…')
    try:
        accounts = list_accounts(session)
    except Exception as e:
        sys.exit(
            f'\n✗  Failed to list accounts: {e}\n\n'
            '   If you see 403/404: enable these APIs in Google Cloud Console:\n'
            '     • Business Profile Account Management API\n'
            '     • Business Profile Information API\n'
            '     • Business Profile Performance API\n'
        )

    if not accounts:
        sys.exit('✗  No GBP accounts found. Check credentials scope and account access.')
    print(f'  Found {len(accounts)} account(s):')
    for i, a in enumerate(accounts):
        # New API uses 'accountName' for the human label and 'name' for the resource path
        label = a.get('accountName') or a.get('name', '?')
        print(f'  [{i}] {label}')

    # Auto-select: prefer account named "Allo Health", fall back to first non-group account
    def _score(a):
        n = (a.get('accountName') or '').lower()
        if 'allo' in n: return 0
        if 'group' in n or 'location' in n: return 2
        return 1
    accounts_sorted = sorted(accounts, key=_score)
    account      = accounts_sorted[0] if len(accounts) >= 1 else accounts[int(input('  Select index: ') or 0)]
    account_name = account['name']          # e.g. 'accounts/123456789'
    label        = account.get('accountName') or account_name
    print(f'  → Using: {label}  ({account_name})')

    # ── Discover locations ─────────────────────────────────────────────────────
    print('\n● Listing locations…')
    try:
        locations = list_locations(session, account_name)
    except Exception as e:
        sys.exit(f'✗  Failed to list locations: {e}')
    print(f'  Found {len(locations)} location(s)')

    # ── Fetch metrics per location (new API is per-location only) ─────────────
    ALL_DASH_KEYS = list(PERF_METRICS.values()) + [
        'impressions_search', 'impressions_maps',
        'queries_indirect', 'queries_direct', 'queries_chain',
    ]
    print(f'\n● Fetching metrics for {len(locations)} location(s)…')
    print('  (new Business Profile Performance API — ~2-4 s per location)')

    # ── Aggregate ──────────────────────────────────────────────────────────────
    network    = {k: zero_series() for k in ALL_DASH_KEYS}
    by_city    = {}
    by_location = {}

    for i, loc in enumerate(locations):
        display = loc.get('title', loc.get('locationName', loc['name']))
        city    = city_from_name(display)
        print(f'  [{i+1}/{len(locations)}] {display}…', end=' ', flush=True)

        ins = fetch_location_all(session, loc)

        if city not in by_city:
            by_city[city] = {k: zero_series() for k in ALL_DASH_KEYS}

        loc_entry = {'name': display, 'city': city}
        for dk in ALL_DASH_KEYS:
            series = ins.get(dk) or zero_series()
            loc_entry[dk]       = series
            network[dk]         = add_series(network[dk], series)
            by_city[city][dk]   = add_series(by_city[city][dk], series)

        by_location[loc['name']] = loc_entry
        print('✓')

    # ── Write output ───────────────────────────────────────────────────────────
    output = {
        'generated':   datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'weeks':       WEEK_KEYS,
        'note': {
            'queries_direct':   'Searches using the business name or address — brand recall / loyalty',
            'queries_indirect': 'Category / keyword discovery searches — new demand entering category',
            'queries_chain':    'Branded chain searches e.g. "allo health near me" — brand awareness',
            'directions':       'Direction requests — best proxy for foot-traffic intent',
            'calls':            'GMB phone-call taps — may overlap with Organic calls in appointment data',
        },
        'network':      network,
        'by_city':      by_city,
        'by_location':  by_location,
    }

    with open(OUTPUT, 'w') as f:
        json.dump(output, f, indent=2)

    print(f'\n✓  Saved → {OUTPUT}')
    print(f'   Weeks : {WEEK_KEYS[0]} … {WEEK_KEYS[-1]}')
    print(f'   Cities: {sorted(c for c in by_city if c != "Other")}')
    print(f'   Locs  : {len(by_location)}')

    # Quick sanity summary
    tot_direct   = sum(x or 0 for x in network['queries_direct'])
    tot_indirect = sum(x or 0 for x in network['queries_indirect'])
    tot_chain    = sum(x or 0 for x in network['queries_chain'])
    grand        = tot_direct + tot_indirect + tot_chain or 1
    print(f'\n   Network query mix (7-wk total):')
    print(f'     Discovery (indirect) : {tot_indirect:>6}  {tot_indirect/grand*100:.0f}%')
    print(f'     Direct               : {tot_direct:>6}  {tot_direct/grand*100:.0f}%')
    print(f'     Branded chain        : {tot_chain:>6}  {tot_chain/grand*100:.0f}%')


if __name__ == '__main__':
    main()
