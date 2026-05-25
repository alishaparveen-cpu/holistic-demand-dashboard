"""
Pull GMB inventory per location: photos, videos, services, products.

Reviews are already in reviews.csv — we just compute totals + STI-specific from there.

Endpoints used:
  mybusiness.googleapis.com/v4/{account}/locations/{loc}/media         (photos/videos)
  mybusinessbusinessinformation.googleapis.com/v1/locations/{loc}?readMask=serviceItems
  mybusiness.googleapis.com/v4/{account}/locations/{loc}/products      (best-effort; usually empty)

Outputs:
  gmb_inventory.csv      per-clinic totals
  gmb_services_raw.json  full service list per location (for STI inspection)
  gmb_media_raw.json     full media metadata per location
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
SLEEP = 0.5

STI_RX = re.compile(r'\b(sti|std|hiv|sexually\s*transmitted|gonorr|syphil|herpes|chlamydia|aids)\b', re.I)


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


def api_get(url, token):
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        return None, f'HTTP {e.code}: {body}'


def fetch_media(account, loc_id, token):
    items = []
    page_token = None
    err = None
    while True:
        params = {'pageSize': 100}
        if page_token:
            params['pageToken'] = page_token
        url = f'https://mybusiness.googleapis.com/v4/{account}/locations/{loc_id}/media?' + urllib.parse.urlencode(params)
        body, err = api_get(url, token)
        if body is None:
            return items, err
        for m in body.get('mediaItems', []):
            items.append({
                'name': m.get('name'),
                'format': m.get('mediaFormat'),    # PHOTO / VIDEO
                'createTime': m.get('createTime'),
                'category': (m.get('locationAssociation') or {}).get('category'),
                'sourceUrl': m.get('sourceUrl'),
            })
        page_token = body.get('nextPageToken')
        if not page_token:
            return items, None
        time.sleep(SLEEP)


def fetch_services(loc_id, token):
    url = f'https://mybusinessbusinessinformation.googleapis.com/v1/locations/{loc_id}?readMask=serviceItems'
    body, err = api_get(url, token)
    if body is None:
        return [], err
    return body.get('serviceItems', []), None


def fetch_products(account, loc_id, token):
    # v4 productLists endpoint — sometimes 404; tolerate
    url = f'https://mybusiness.googleapis.com/v4/{account}/locations/{loc_id}/productLists'
    body, err = api_get(url, token)
    if body is None:
        return [], err
    return body.get('productLists', []), None


def service_label(svc):
    """Get a human label from a serviceItem (structuredServiceItem.serviceTypeId or freeFormServiceItem.label.displayName)."""
    if 'freeFormServiceItem' in svc:
        return (svc['freeFormServiceItem'].get('label') or {}).get('displayName', '')
    if 'structuredServiceItem' in svc:
        return svc['structuredServiceItem'].get('serviceTypeId', '')
    return ''


def main():
    creds = load_creds()
    print('→ refreshing token...')
    token = get_token(creds)
    print('  OK')

    locs = json.load(open(HERE / 'gbp_locations.json'))
    print(f'→ {len(locs)} locations')

    inventory = []
    services_raw = {}
    media_raw = {}
    failed_media = 0
    failed_svcs = 0
    failed_prods = 0
    t0 = time.time()

    for i, loc in enumerate(locs, 1):
        name = loc.get('name', '')
        loc_id = name.split('/')[-1] if name else None
        account = loc.get('_account') or 'accounts/104278284314268556784'
        if not loc_id:
            continue
        title = loc.get('title', '')[:80]
        city = (loc.get('storefrontAddress') or {}).get('locality') or '?'
        labels = loc.get('labels') or []

        # 1. Media
        media, err = fetch_media(account, loc_id, token)
        if err:
            failed_media += 1
        media_raw[loc_id] = media
        photos = sum(1 for m in media if m.get('format') == 'PHOTO')
        videos = sum(1 for m in media if m.get('format') == 'VIDEO')
        time.sleep(SLEEP)

        # 2. Services
        svcs, err = fetch_services(loc_id, token)
        if err:
            failed_svcs += 1
        services_raw[loc_id] = svcs
        svc_labels = [service_label(s) for s in svcs]
        sti_svcs = [lbl for lbl in svc_labels if lbl and STI_RX.search(lbl)]
        time.sleep(SLEEP)

        # 3. Products
        prods, err = fetch_products(account, loc_id, token)
        if err and '404' not in (err or ''):
            failed_prods += 1
        prod_count = sum(len(p.get('items', [])) for p in prods)
        time.sleep(SLEEP)

        inventory.append({
            'location_id': loc_id,
            'store_code': loc.get('storeCode', ''),
            'title': title,
            'city': city,
            'tier': 'T1' if 'T1' in labels else ('T2' if 'T2' in labels else '?'),
            'state': next((l for l in labels if l not in ('T1', 'T2')), ''),
            'photos': photos,
            'videos': videos,
            'services_total': len(svcs),
            'services_sti': len(sti_svcs),
            'services_sti_list': ' | '.join(sti_svcs)[:200],
            'products': prod_count,
        })
        if i % 5 == 0 or i == len(locs):
            print(f'  …{i}/{len(locs)}  ({time.time()-t0:.0f}s)  failed: media={failed_media} svcs={failed_svcs} prods={failed_prods}')

    # Save
    (HERE / 'gmb_services_raw.json').write_text(json.dumps(services_raw, indent=1, ensure_ascii=False))
    (HERE / 'gmb_media_raw.json').write_text(json.dumps(media_raw, indent=1))

    # Reviews totals from reviews.csv
    rev_total = {}
    rev_sti = {}
    rev_path = HERE / 'reviews.csv'
    if rev_path.exists():
        with open(rev_path) as f:
            for r in csv.DictReader(f):
                lid = r['location_id']
                rev_total[lid] = rev_total.get(lid, 0) + 1
                if STI_RX.search(r.get('text') or '') or STI_RX.search(r.get('title') or ''):
                    rev_sti[lid] = rev_sti.get(lid, 0) + 1

    for row in inventory:
        lid = row['location_id']
        row['reviews_total'] = rev_total.get(lid, 0)
        row['reviews_sti'] = rev_sti.get(lid, 0)
        row['total_inventory'] = (row['photos'] + row['videos'] + row['services_total']
                                  + row['products'] + row['reviews_total'])
        row['total_sti'] = row['services_sti'] + row['reviews_sti']

    keys = ['location_id', 'store_code', 'title', 'city', 'tier', 'state',
            'photos', 'videos', 'services_total', 'services_sti', 'services_sti_list',
            'products', 'reviews_total', 'reviews_sti', 'total_inventory', 'total_sti']
    with open(HERE / 'gmb_inventory.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in inventory:
            w.writerow(r)
    print(f'\n✓ saved gmb_inventory.csv ({len(inventory)} rows)')
    print(f'  failed: media={failed_media} services={failed_svcs} products={failed_prods}')


if __name__ == '__main__':
    main()
