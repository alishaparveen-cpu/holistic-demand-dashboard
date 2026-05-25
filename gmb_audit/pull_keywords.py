"""
Pull GBP Search Keywords for all Allo Health locations.

Uses the OAuth refresh token from /root/.allo-secrets/mcp_config.json.
Hits:
  - oauth2.googleapis.com (refresh token → access token)
  - mybusinessaccountmanagement.googleapis.com (list accounts)
  - mybusinessbusinessinformation.googleapis.com (list locations under each account)
  - businessprofileperformance.googleapis.com (search keywords per location, monthly)

Outputs:
  - accounts.json         — what accounts are accessible
  - locations.json        — all locations under those accounts
  - search_keywords.csv   — location_id, location_name, keyword, impressions, month

Note: GBP Performance API requires the location to be VERIFIED. Suspended/pending
profiles will return empty results. Run includes a 1.5s sleep between calls to
stay under Google's rate limit (~600/min).
"""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

CREDS_PATH = Path("/root/.allo-secrets/mcp_config.json")
OUT_DIR = Path(__file__).parent
TOKEN_URI = "https://oauth2.googleapis.com/token"


def load_gbp_creds() -> dict:
    with open(CREDS_PATH) as f:
        cfg = json.load(f)
    env = cfg["mcpServers"]["@allo/gbp"]["env"]
    return {
        "client_id": env["GBP_CLIENT_ID"],
        "client_secret": env["GBP_CLIENT_SECRET"],
        "refresh_token": env["GBP_REFRESH_TOKEN"],
    }


def get_access_token(creds: dict) -> str:
    data = urllib.parse.urlencode({
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_URI, data=data, method="POST")
    with urllib.request.urlopen(req) as r:
        body = json.loads(r.read())
    return body["access_token"]


def api_get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  HTTP {e.code} {e.reason}\n  URL: {url}\n  Body: {body[:500]}", file=sys.stderr)
        raise


def list_accounts(token: str) -> list[dict]:
    url = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
    out = api_get(url, token)
    return out.get("accounts", [])


def list_locations_for_account(account_name: str, token: str) -> list[dict]:
    locs = []
    page_token = None
    while True:
        fields = "name,title,storeCode,storefrontAddress,categories,metadata,labels"
        url = f"https://mybusinessbusinessinformation.googleapis.com/v1/{account_name}/locations?readMask={fields}&pageSize=100"
        if page_token:
            url += f"&pageToken={page_token}"
        out = api_get(url, token)
        locs.extend(out.get("locations", []))
        page_token = out.get("nextPageToken")
        if not page_token:
            break
        time.sleep(1)
    return locs


def get_search_keywords(location_id: str, token: str, year: int, month: int) -> list[dict]:
    """location_id should be the bare numeric ID, not 'locations/XXX'."""
    base = "https://businessprofileperformance.googleapis.com/v1"
    url = (
        f"{base}/locations/{location_id}/searchkeywords/impressions/monthly"
        f"?monthlyRange.startMonth.year={year}&monthlyRange.startMonth.month={month}"
        f"&monthlyRange.endMonth.year={year}&monthlyRange.endMonth.month={month}"
    )
    out = api_get(url, token)
    return out.get("searchKeywordsCounts", [])


def main():
    creds = load_gbp_creds()
    print("→ Refreshing access token...", flush=True)
    token = get_access_token(creds)
    print("  OK", flush=True)

    print("→ Listing accounts...", flush=True)
    accounts = list_accounts(token)
    print(f"  {len(accounts)} accounts", flush=True)
    with open(OUT_DIR / "gbp_accounts.json", "w") as f:
        json.dump(accounts, f, indent=2)

    all_locs = []
    for acc in accounts:
        name = acc.get("name")
        print(f"→ Locations in {name} ({acc.get('accountName','?')})...", flush=True)
        try:
            locs = list_locations_for_account(name, token)
        except Exception as e:
            print(f"  ERR: {e}", file=sys.stderr)
            continue
        print(f"  {len(locs)} locations", flush=True)
        for L in locs:
            L["_account"] = name
        all_locs.extend(locs)
        time.sleep(1)

    with open(OUT_DIR / "gbp_locations.json", "w") as f:
        json.dump(all_locs, f, indent=2)
    print(f"→ Saved {len(all_locs)} total locations to gbp_locations.json", flush=True)

    # Search keywords for last full month
    today = date.today()
    first_of_this_month = today.replace(day=1)
    last_full_month_end = first_of_this_month - timedelta(days=1)
    year, month = last_full_month_end.year, last_full_month_end.month
    print(f"→ Pulling search keywords for {year}-{month:02d}", flush=True)

    rows = []
    failed = []
    for i, L in enumerate(all_locs, 1):
        loc_name = L.get("name", "")  # e.g. 'locations/12345...'
        loc_id = loc_name.split("/")[-1]
        title = L.get("title", "")
        store_code = L.get("storeCode", "")
        try:
            kws = get_search_keywords(loc_id, token, year, month)
        except Exception as e:
            failed.append((store_code, title, str(e)))
            continue
        for kw in kws:
            rows.append({
                "store_code": store_code,
                "location_id": loc_id,
                "title": title,
                "month": f"{year}-{month:02d}",
                "keyword": kw.get("searchKeyword"),
                "impressions_lower": (kw.get("insightsValue") or {}).get("threshold") or (kw.get("insightsValue") or {}).get("value"),
            })
        if i % 5 == 0:
            print(f"  …{i}/{len(all_locs)} processed, {len(rows)} keyword rows, {len(failed)} failed", flush=True)
        time.sleep(1.5)

    with open(OUT_DIR / "search_keywords.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["store_code","location_id","title","month","keyword","impressions_lower"])
        w.writeheader()
        w.writerows(rows)
    print(f"\n✓ Saved {len(rows)} keyword rows from {len(all_locs)-len(failed)} locations", flush=True)
    if failed:
        print(f"  {len(failed)} locations failed — see failures.log", flush=True)
        with open(OUT_DIR / "failures.log", "w") as f:
            for sc, t, err in failed:
                f.write(f"{sc}\t{t}\t{err}\n")


if __name__ == "__main__":
    main()
