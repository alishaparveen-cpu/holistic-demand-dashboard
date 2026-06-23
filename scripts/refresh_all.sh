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
step "GA total spend (pull_ga_total_spend)" python3 scripts/pull_ga_total_spend.py   # native Google spend for efficiency
step "GA gclid leads→bookings (SQL)"      bash -c 'cat scripts/fetch_ga_leads.sql | python3 scripts/redshift_query.py > /tmp/ga_leads.tsv'
step "GA funnel build (build_ga_funnel)"  python3 scripts/build_ga_funnel.py
step "Per-campaign leads (enrich_campaign_leads)" python3 scripts/enrich_campaign_leads.py
step "Total Google leads by city (pull_ga_city_leads)" python3 scripts/pull_ga_city_leads.py
step "Indiranagar paid reach (location asset)" python3 scripts/pull_indiranagar_google_asset.py   # clinic-level Google paid for the Indiranagar funnel

echo "── Redshift core (needs aws sso login) ──"
step "Leads by source (build_leads)"      python3 scripts/build_leads.py   # must precede scorecard (leads denom)
step "Organic sub-channels (pull_organic_sub)" python3 scripts/pull_organic_sub.py   # WhatsApp/PC-Inbound/etc. for efficiency organic drill-down
step "Scorecard (build_scorecard)"        python3 scripts/build_scorecard.py
step "Phase-2 metrics (build_phase2)"     python3 scripts/build_phase2.py
step "Diagnostic RCA (build_diagnostic)"  python3 scripts/build_diagnostic.py
step "Roster availability (build_roster)"    python3 scripts/build_roster.py
step "GMB review velocity (build_reviews)"  python3 scripts/build_reviews.py
step "Lead→conversion (build_lead_conv)"  python3 scripts/build_lead_conv.py
step "Contact mode (build_contact_mode)"  python3 scripts/build_contact_mode.py
step "Booking hour×day (build_booking_hod)" python3 scripts/build_booking_hod.py
step "Avail hour×day (build_avail_hod)"     python3 scripts/build_avail_hod.py
step "Booking cube (build_booking_source)"  python3 scripts/build_booking_source.py
step "Re-book gap (build_rebook_gap)"        python3 scripts/build_rebook_gap.py
step "Booking episodes (clean funnel)"      python3 scripts/build_booking_episodes.py
step "Demand superset (relevancy/funnel)"   python3 scripts/build_demand_superset.py
step "Lead age (build_lead_age)"            python3 scripts/build_lead_age.py
step "Lead maturation (build_lead_maturation)" python3 scripts/build_lead_maturation.py
step "Lead cohort (build_lead_cohort)"      python3 scripts/build_lead_cohort.py
step "Demand drops view (build_drops)"      python3 scripts/build_drops.py
step "Leads total (build_leads_total)"      python3 scripts/build_leads_total.py
step "Practo booked (build_practo_booked)"  python3 scripts/build_practo_booked.py
step "Practo cohort conv (build_practo_conv)" python3 scripts/build_practo_conv.py
# ── Category pipeline (gross bookings + doctor level) — chain: pull → data.json → channel cube ──
step "Category bookings pull (fetch_bookings)" python3 scripts/fetch_bookings.py
step "Category data build (rebuild_data)"      python3 scripts/rebuild_data.py
step "Channel cube (build_channel_data)"       python3 scripts/build_channel_data.py
step "Efficiency RS-native (build_efficiency_rs)" python3 scripts/build_efficiency_rs.py
step "Weekly review (network leads/book/done)" python3 scripts/build_weekly_review.py
step "Indiranagar AI call leads (channel×category)" python3 scripts/pull_indiranagar_calls.py
step "Indiranagar bottom funnel (booked/done/purchased/rev by cat)" python3 scripts/pull_indiranagar_bottom.py
step "Indiranagar funnel assemble"            python3 scripts/assemble_indiranagar.py   # combines geo+gmb+leads+bottom → data_indiranagar.json

echo "── Sheets / API (no Redshift creds needed) ──"
step "Practo leads (build_practo_leads)"  python3 scripts/build_practo_leads.py
step "Channel efficiency (build_efficiency)" python3 scripts/build_efficiency.py

echo "── Optional / API ──"
step "GMB insights (pull_gmb_insights)"   python3 scripts/pull_gmb_insights.py
step "Negative reviews (build_reviews_neg_gbp)" python3 scripts/build_reviews_neg_gbp.py

echo "════════════════════════════════════════════════"
printf "Done: %d OK, %d FAIL" "$PASS" "$FAIL"
[ "$FAIL" -gt 0 ] && printf " — failed steps:%b\n" "$FAILED_STEPS" || echo " — all good."
echo "Review changes with: git status --short data_*.json"
# Fail the run (red ✗ in CI) when most steps fail — almost always a missing-credentials problem.
# Without this the workflow reports a false "success" while pulling nothing (e.g. empty GitHub Secrets).
if [ "$FAIL" -ge "$PASS" ]; then
  echo "✗ ABORT: $FAIL of $((PASS+FAIL)) steps failed — likely missing credentials (AWS / Google Ads / GBP secrets). Check GitHub → Settings → Secrets." >&2
  exit 1
fi
