#!/usr/bin/env python3
"""Which Google-Ads CALL phone number is attached to which campaign (esp. the online/brand ones).
Answers: are the online call numbers dedicated per-campaign, or shared? Run: source ~/.google_ads.env; python3 scripts/pull_call_numbers.py"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import pull_ga_city_paid as G

def main():
    c = G._creds(); tok = G._token(c)
    # call assets linked at campaign level
    rows = G.gaql(tok, c, """
      SELECT campaign.name, campaign.status, asset.call_asset.phone_number, asset.name
      FROM campaign_asset WHERE campaign_asset.field_type = 'CALL'""")
    seen = {}
    for r in rows:
        nm = r.get("campaign", {}).get("name", "?"); st = r.get("campaign", {}).get("status", "")
        ph = (r.get("asset", {}).get("callAsset", {}) or {}).get("phoneNumber") or r.get("asset", {}).get("name")
        seen.setdefault((nm, st), set()).add(ph)
    print("=== CAMPAIGN-LEVEL call assets ===")
    for (nm, st), phs in sorted(seen.items()):
        if "nline" in nm or "Brand" in nm or "ONL" in nm or "ROI" in nm or "CC_" in nm:
            print(f"  {nm}  [{st}]  ->  {sorted(phs)}")
    # also account-level call assets (a shared number applied to all)
    rows2 = G.gaql(tok, c, """SELECT asset.call_asset.phone_number, asset.name FROM customer_asset
      WHERE customer_asset.field_type = 'CALL'""")
    acct = sorted({(r.get("asset", {}).get("callAsset", {}) or {}).get("phoneNumber") or r.get("asset", {}).get("name") for r in rows2})
    print("\n=== ACCOUNT-LEVEL (shared) call assets ===")
    for a in acct: print("  ", a)

if __name__ == "__main__":
    main()
