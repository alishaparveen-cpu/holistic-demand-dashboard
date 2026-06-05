#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Weekly data refresh for the demand dashboard — the "refresh button".
# Rebuilds the live data JSONs and deploys (commit + push to main → GitHub Pages).
#
#   Redshift pulls   (need AWS SSO):  data_diagnostic.json, data_reviews_neg.json
#   Google Ads pull  (need GA creds): data_ga_city.json
#
# SETUP (once):
#   • AWS SSO:   aws sso login --profile redshift-data
#   • GA creds:  put the 4 GOOGLE_ADS_* exports in scripts/.ga_creds.env  (gitignored),
#                or have them already in your environment.
#
# RUN:   bash scripts/refresh.sh
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
export AWS_PROFILE="${AWS_PROFILE:-redshift-data}"
ok=(); fail=()

echo "── 1/3  Redshift: diagnostic (bookings · disposition · availability)"
if python3 scripts/build_diagnostic.py; then ok+=("data_diagnostic.json"); else fail+=("diagnostic — is your AWS SSO session valid? run: aws sso login --profile redshift-data"); fi

echo "── 2/4  Redshift: network total leads · GBP: live negative reviews"
if python3 scripts/build_leads_total.py; then ok+=("data_leads_total.json"); else fail+=("leads_total"); fi
if python3 scripts/build_lead_age.py; then ok+=("data_lead_age.json"); else fail+=("lead_age"); fi
if python3 scripts/build_demand_superset.py; then ok+=("data_demand_funnel.json"); else fail+=("demand_funnel"); fi
if python3 scripts/build_practo_booked.py; then ok+=("data_practo_booked.json"); else fail+=("practo_booked"); fi
# Negatives come LIVE from the Google Business Profile API (warehouse external_reviews ETL stopped 2026-05-06).
[ -f "$HOME/.allo_gbp.env" ] && { set -a; . "$HOME/.allo_gbp.env"; set +a; }
if [ -n "${GBP_REFRESH_TOKEN:-}" ] && python3 scripts/build_reviews_neg_gbp.py; then ok+=("data_reviews_neg.json (GBP)");
elif python3 scripts/build_reviews_neg.py; then ok+=("data_reviews_neg.json (warehouse fallback)"); else fail+=("reviews_neg"); fi

echo "── 3/4  Google Ads: city-level health + campaign roster/trends"
for cf in "$HOME/.allo_ga.env" scripts/.ga_creds.env; do [ -f "$cf" ] && { set -a; . "$cf"; set +a; }; done
if [ -z "${GOOGLE_ADS_REFRESH_TOKEN:-}" ]; then
  fail+=("google-ads — no creds (set GOOGLE_ADS_* or scripts/.ga_creds.env)")
elif python3 scripts/pull_ga_city.py; then ok+=("data_ga_city.json"); else fail+=("google-ads pull"); fi

echo "── 4/4  GBP: GMB profile Insights (searches · interactions) per clinic"
[ -f "$HOME/.allo_gbp.env" ] && { set -a; . "$HOME/.allo_gbp.env"; set +a; }
if [ -z "${GBP_REFRESH_TOKEN:-}" ]; then
  fail+=("gmb-insights — no creds (set GBP_* in ~/.allo_gbp.env)")
elif python3 scripts/pull_gmb_insights.py; then ok+=("data_gmb_insights.json"); else fail+=("gmb-insights pull"); fi

echo
echo "Refreshed: ${ok[*]:-none}"
[ ${#fail[@]} -gt 0 ] && printf 'Skipped/failed:\n  - %s\n' "${fail[@]}"

# ── deploy: commit only the data files that changed, then push main ──
CHANGED=$(git status --porcelain data_diagnostic.json data_reviews_neg.json data_ga_city.json data_leads_total.json data_gmb_insights.json data_lead_age.json data_demand_funnel.json data_practo_booked.json | awk '{print $2}')
if [ -z "$CHANGED" ]; then echo "No data changes — nothing to deploy."; exit 0; fi
echo; echo "Deploying: $CHANGED"
git add $CHANGED
git commit -q -m "Weekly data refresh ($(date +%Y-%m-%d)): ${ok[*]}" || { echo "commit failed"; exit 1; }
BR=$(git rev-parse --abbrev-ref HEAD)
git checkout -q main && git merge -q --ff-only "$BR" && git push -q origin main && git checkout -q "$BR"
echo "✓ Deployed to main → GitHub Pages."
