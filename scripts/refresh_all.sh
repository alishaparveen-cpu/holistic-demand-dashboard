#!/usr/bin/env bash
# One-command data refresh for the dashboard. Regenerates the Redshift- and API-driven
# data files, reporting OK / FAIL per step (never aborts the whole run on one failure).
#
# Prereqs:
#   • AWS SSO:  aws sso login --profile redshift-data       (for the Redshift steps)
#   • Google Ads creds:  source ~/.allo_google_ads.env       (for the GA steps)
# Usage:  bash scripts/refresh_all.sh        # from repo root (or anywhere; it cd's itself)
#
# NOTE: data.json (core bookings funnel) still has manual Google-Sheet inputs per
# DATA_SOURCES.md and is NOT regenerated here — that step remains manual for now.

cd "$(dirname "$0")/.." || exit 1
export AWS_REGION="${AWS_REGION:-ap-south-1}"
# Local run → use the SSO profile. CI run (IAM keys in env) → leave AWS_PROFILE unset.
if [ -z "$AWS_ACCESS_KEY_ID" ]; then export AWS_PROFILE="${AWS_PROFILE:-redshift-data}"; fi
[ -f "$HOME/.allo_google_ads.env" ] && source "$HOME/.allo_google_ads.env"

PASS=0; FAIL=0; FAILED_STEPS=""
step () {  # step "Label" command...
  local label="$1"; shift
  printf "→ %-44s" "$label"
  if out=$("$@" 2>&1); then
    echo "OK   ${out##*$'\n'}"; PASS=$((PASS+1))
  else
    echo "FAIL"; echo "    $out" | tail -3 | sed 's/^/    /'
    FAIL=$((FAIL+1)); FAILED_STEPS="$FAILED_STEPS\n  ✗ $label"
  fi
}
echo "════ Dashboard data refresh · $(date '+%Y-%m-%d %H:%M') ════"

echo "── Google Ads (needs ~/.allo_google_ads.env) ──"
step "GA city health (pull_ga_city)"      python3 scripts/pull_ga_city.py
step "GA daily metrics (pull_ga_daily)"   python3 scripts/pull_ga_daily.py
step "GA gclid leads→bookings (SQL)"      bash -c 'cat scripts/fetch_ga_leads.sql | python3 scripts/redshift_query.py > /tmp/ga_leads.tsv'
step "GA funnel build (build_ga_funnel)"  python3 scripts/build_ga_funnel.py

echo "── Redshift core (needs aws sso login) ──"
step "Scorecard (build_scorecard)"        python3 scripts/build_scorecard.py
step "Phase-2 metrics (build_phase2)"     python3 scripts/build_phase2.py
step "Diagnostic RCA (build_diagnostic)"  python3 scripts/build_diagnostic.py

echo "── Optional / API ──"
step "GMB insights (pull_gmb_insights)"   python3 scripts/pull_gmb_insights.py

echo "════════════════════════════════════════════════"
printf "Done: %d OK, %d FAIL" "$PASS" "$FAIL"
[ "$FAIL" -gt 0 ] && printf " — failed steps:%b\n" "$FAILED_STEPS" || echo " — all good."
echo "Review changes with: git status --short data_*.json"
