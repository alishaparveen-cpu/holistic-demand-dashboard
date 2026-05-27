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

def parse_iso_date(s: str) -> datetime.date | None:
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
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            print('ℹ  Token refreshed.')
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

# ── API helpers (raw requests) ─────────────────────────────────────────────────
# Using requests rather than discovery client to avoid the v4 discovery URL issue.

def api_get(session, url, params=None):
    r = session.get(url, params=params)
    r.raise_for_status()
    return r.json()

def api_post(session, url, body):
    r = session.post(url, json=body)
    if not r.ok:
        print(f'  ⚠  POST {url} → {r.status_code}: {r.text[:300]}')
    r.raise_for_status()
    return r.json()

# ── List GMB accounts ──────────────────────────────────────────────────────────
def list_accounts(session):
    data = api_get(session, 'https://mybusiness.googleapis.com/v4/accounts')
    return data.get('accounts', [])

# ── List all locations under an account ───────────────────────────────────────
def list_locations(session, account_name):
    locs, page_token = [], None
    while True:
        params = {'pageSize': 100}
        if page_token:
            params['pageToken'] = page_token
        data = api_get(session,
                       f'https://mybusiness.googleapis.com/v4/{account_name}/locations',
                       params=params)
        locs.extend(data.get('locations', []))
        page_token = data.get('nextPageToken')
        if not page_token:
            break
    return locs

# ── Fetch Insights for a batch of up to 10 locations ──────────────────────────
def fetch_insights_batch(session, account_name, location_names):
    """
    Returns: { location_name → { dash_key → [val_wk0, val_wk1, ...] } }
    where wk0 = most recent (WEEK_KEYS[0]).
    """
    end_dt   = datetime.date.today()
    start_dt = end_dt - datetime.timedelta(weeks=10)

    body = {
        'locationNames': location_names,
        'basicRequest': {
            'metricRequests': [
                {'metric': m} for m in METRIC_MAP
            ],
            'timeRange': {
                'startTime': f'{start_dt.isoformat()}T00:00:00Z',
                'endTime':   f'{end_dt.isoformat()}T23:59:59Z',
            },
        },
    }

    try:
        resp = api_post(
            session,
            f'https://mybusiness.googleapis.com/v4/{account_name}/locations:reportInsights',
            body,
        )
    except Exception as e:
        print(f'  ⚠  reportInsights batch failed: {e}')
        return {}

    result = {}
    for loc_insight in resp.get('locationMetrics', []):
        loc_name = loc_insight['locationName']
        result[loc_name] = {v: zero_series() for v in METRIC_MAP.values()}

        for mv in loc_insight.get('metricValues', []):
            api_key  = mv.get('metric')
            dash_key = METRIC_MAP.get(api_key)
            if not dash_key:
                continue

            # Build weekly lookup from dimensional values
            weekly = {}
            for dv in mv.get('dimensionalValues', []):
                ts = (dv.get('timeDimension') or {}).get('timeRange', {}).get('startTime', '')
                if not ts:
                    # Some responses put the value directly without time dimension
                    continue
                dt = parse_iso_date(ts)
                if not dt:
                    continue
                wk = monday_of(dt)
                # Value may be nested differently across API versions
                raw_val = (
                    dv.get('value')
                    or (dv.get('metricOption') and None)   # guard
                )
                if isinstance(raw_val, dict):
                    raw_val = raw_val.get('value') or raw_val.get('intValue') or 0
                try:
                    weekly[wk] = int(str(raw_val).replace(',', ''))
                except (ValueError, TypeError):
                    weekly[wk] = 0

            # Also check totalValue (some v4 versions use this for weekly rolled-up)
            tv = mv.get('totalValue')
            if tv and not weekly:
                try:
                    total = int(str(tv.get('value', 0)).replace(',', ''))
                    # Spread across all weeks (best-effort when granular data absent)
                    weekly = {wk: total // N_WEEKS for wk in WEEK_KEYS}
                except (ValueError, TypeError):
                    pass

            result[loc_name][dash_key] = [weekly.get(wk) for wk in WEEK_KEYS]

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
        sys.exit(f'✗  Failed to list accounts: {e}\n'
                 '   Check that the Google My Business API (v4) is enabled in your Cloud project.')

    if not accounts:
        sys.exit('✗  No GMB accounts found. Check credentials scope and account access.')
    print(f'  Found {len(accounts)} account(s):')
    for i, a in enumerate(accounts):
        print(f'  [{i}] {a.get("accountName","?")}  ({a["name"]})')

    account = accounts[0] if len(accounts) == 1 else accounts[int(input('  Select index: ') or 0)]
    account_name = account['name']
    print(f'  → Using: {account.get("accountName","?")}')

    # ── Discover locations ─────────────────────────────────────────────────────
    print('\n● Listing locations…')
    try:
        locations = list_locations(session, account_name)
    except Exception as e:
        sys.exit(f'✗  Failed to list locations: {e}')
    print(f'  Found {len(locations)} location(s)')

    # ── Fetch Insights in batches of 10 ───────────────────────────────────────
    print('\n● Fetching weekly insights (this may take 30–60 s)…')
    all_insights = {}
    loc_names = [l['name'] for l in locations]
    n_batches  = (len(loc_names) + 9) // 10

    for bi in range(n_batches):
        batch = loc_names[bi*10 : (bi+1)*10]
        print(f'  Batch {bi+1}/{n_batches}  ({len(batch)} locs)…', end=' ', flush=True)
        result = fetch_insights_batch(session, account_name, batch)
        all_insights.update(result)
        print('done')

    # ── Aggregate ──────────────────────────────────────────────────────────────
    print('\n● Aggregating by city…')
    network    = {v: zero_series() for v in METRIC_MAP.values()}
    by_city    = {}
    by_location = {}

    for loc in locations:
        loc_name    = loc['name']
        display     = loc.get('locationName', loc_name)
        city        = city_from_name(display)
        ins         = all_insights.get(loc_name, {})

        loc_entry   = {'name': display, 'city': city}
        if city not in by_city:
            by_city[city] = {v: zero_series() for v in METRIC_MAP.values()}

        for dash_key in METRIC_MAP.values():
            series = ins.get(dash_key) or zero_series()
            loc_entry[dash_key]       = series
            network[dash_key]         = add_series(network[dash_key], series)
            by_city[city][dash_key]   = add_series(by_city[city][dash_key], series)

        by_location[loc_name] = loc_entry

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
