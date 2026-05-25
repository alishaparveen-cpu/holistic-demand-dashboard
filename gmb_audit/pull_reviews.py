"""
Pull GMB reviews for all 68 Allo Health locations via Business Profile v4 API.

Outputs:
  reviews.json — raw nested per-location response
  reviews.csv  — flat: location_id, store_code, title, city, review_id, stars(1-5),
                       create_time, text, has_reply, reply_time

Uses OAuth refresh token from /root/.allo-secrets/mcp_config.json.
"""
from __future__ import annotations
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
CREDS = Path('/root/.allo-secrets/mcp_config.json')
LOCS_FILE = HERE / 'gbp_locations.json'
OUT_JSON = HERE / 'reviews.json'
OUT_CSV = HERE / 'reviews.csv'
SLEEP = 0.6  # seconds between calls — conservative

STAR_MAP = {'ONE': 1, 'TWO': 2, 'THREE': 3, 'FOUR': 4, 'FIVE': 5,
            'STAR_RATING_UNSPECIFIED': None}


def load_creds():
    cfg = json.load(open(CREDS))
    env = cfg['mcpServers']['@allo/gbp']['env']
    return {
        'client_id': env['GBP_CLIENT_ID'],
        'client_secret': env['GBP_CLIENT_SECRET'],
        'refresh_token': env['GBP_REFRESH_TOKEN'],
    }


def get_token(creds):
    data = urllib.parse.urlencode({**creds, 'grant_type': 'refresh_token'}).encode()
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data, method='POST')
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())['access_token']


def extract_city(addr):
    if not addr:
        return None
    return addr.get('locality') or (addr.get('addressLines') or [None])[-1]


def fetch_reviews(account, loc_id, token):
    out = []
    page_token = None
    while True:
        params = {'pageSize': 50}
        if page_token:
            params['pageToken'] = page_token
        url = f'https://mybusiness.googleapis.com/v4/{account}/locations/{loc_id}/reviews?' + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
        try:
            with urllib.request.urlopen(req) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            print(f'    HTTP {e.code} on {loc_id}: {e.read().decode()[:200]}', file=sys.stderr)
            return out, None, None
        for rv in body.get('reviews', []):
            out.append(rv)
        page_token = body.get('nextPageToken')
        if not page_token:
            return out, body.get('averageRating'), body.get('totalReviewCount')
        time.sleep(SLEEP)


def main():
    creds = load_creds()
    print('→ refreshing token...')
    token = get_token(creds)
    print('  OK')

    locs = json.load(open(LOCS_FILE))
    print(f'→ {len(locs)} locations to pull')

    all_data = []
    csv_rows = []
    failed = []
    t0 = time.time()
    for i, loc in enumerate(locs, 1):
        name = loc.get('name', '')           # "locations/12345"
        account = loc.get('_account', '')     # "accounts/12345" (added by previous puller)
        if not account:
            account = 'accounts/104278284314268556784'  # default Allo Health
        loc_id = name.split('/')[-1] if name else None
        if not loc_id:
            failed.append((loc.get('storeCode'), 'no name'))
            continue
        title = loc.get('title', '')
        sc = loc.get('storeCode', '')
        city = extract_city(loc.get('storefrontAddress', {}))
        reviews, avg, total = fetch_reviews(account, loc_id, token)
        all_data.append({
            'location_id': loc_id,
            'store_code': sc,
            'title': title,
            'city': city,
            'average_rating': avg,
            'total_review_count': total,
            'reviews_pulled': len(reviews),
            'reviews': reviews,
        })
        for rv in reviews:
            csv_rows.append({
                'location_id': loc_id,
                'store_code': sc,
                'title': title,
                'city': city,
                'review_id': rv.get('reviewId'),
                'stars': STAR_MAP.get(rv.get('starRating')),
                'create_time': rv.get('createTime'),
                'update_time': rv.get('updateTime'),
                'text': (rv.get('comment') or '').replace('\n', ' ').strip(),
                'reviewer': (rv.get('reviewer') or {}).get('displayName', ''),
                'has_reply': 'reviewReply' in rv,
                'reply_time': (rv.get('reviewReply') or {}).get('updateTime'),
            })
        if i % 5 == 0 or i == len(locs):
            elapsed = time.time() - t0
            print(f'  …{i}/{len(locs)}  reviews={len(csv_rows)}  ({elapsed:.0f}s elapsed)')
        time.sleep(SLEEP)

    OUT_JSON.write_text(json.dumps(all_data, indent=1, ensure_ascii=False))
    with open(OUT_CSV, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()) if csv_rows else
                           ['location_id', 'store_code', 'title', 'city', 'review_id', 'stars',
                            'create_time', 'update_time', 'text', 'reviewer', 'has_reply', 'reply_time'])
        w.writeheader()
        for r in csv_rows:
            w.writerow(r)
    print(f'✓ saved {len(csv_rows)} reviews from {len(all_data)} locations to reviews.csv')
    if failed:
        print(f'  {len(failed)} failed:', failed[:5])


if __name__ == '__main__':
    main()
