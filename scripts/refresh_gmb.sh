#!/usr/bin/env bash
# refresh_gmb.sh — one command to refresh the GMB tab end-to-end and publish.
#
#   ./scripts/refresh_gmb.sh
#
# Runs the three pulls that feed data_gmb_tab.json, rebuilds the cube, and (unless --no-push)
# commits + pushes so GitHub Pages serves the fresh data. All three pulls compute their week
# grid dynamically, so this is zero-touch — safe to run daily.
#
# Needs:
#   • GBP OAuth creds  → ~/.allo_gbp.env   (GBP_CLIENT_ID / GBP_CLIENT_SECRET / GBP_REFRESH_TOKEN)
#   • Redshift SSO     → AWS_PROFILE=redshift-data  (run: AWS_PROFILE=redshift-data aws sso login)
#   • DataForSEO auth  → ~/.allo_dfs_auth   (only if you also refresh competition; not needed here)
set -uo pipefail
cd "$(dirname "$0")/.."
export AWS_PROFILE="${AWS_PROFILE:-redshift-data}"
PUSH=1; [ "${1:-}" = "--no-push" ] && PUSH=0
ok(){ printf '\n\033[1;32m✓ %s\033[0m\n' "$1"; }
warn(){ printf '\n\033[1;33m! %s\033[0m\n' "$1"; }
step(){ printf '\n\033[1;36m▶ %s\033[0m\n' "$1"; }

# 0) preflight: SSO still valid? (reviews pulls need it)
step "checking Redshift SSO"
if ! aws sts get-caller-identity >/dev/null 2>&1; then
  warn "SSO expired — run:  AWS_PROFILE=$AWS_PROFILE aws sso login"; exit 1
fi
ok "SSO valid"

# 1) GBP Performance API — impressions / calls / website / directions (dynamic week grid)
step "pull_gmb_insights (Google Business Profile Performance API)"
if [ -f "$HOME/.allo_gbp.env" ]; then
  set -a; . "$HOME/.allo_gbp.env"; set +a
  python3 scripts/pull_gmb_insights.py || warn "pull_gmb_insights failed — keeping last insights"
else
  warn "~/.allo_gbp.env missing — skipping GBP insights (impressions won't advance)"
fi

# 2) reviews velocity + rating + negatives (Redshift external_reviews)
step "build_reviews (allo_health.external_reviews)"
python3 scripts/build_reviews.py || warn "build_reviews failed — keeping last reviews"

# 3) category-tagged review text (Redshift external_reviews text)
step "pull_gmb_review_cat (SH/STI/MH keyword tagging)"
python3 scripts/pull_gmb_review_cat.py || warn "pull_gmb_review_cat failed — keeping last review categories"

# 4) assemble the cube the tab reads
step "build_gmb_cube → data_gmb_tab.json"
python3 scripts/build_gmb_cube.py || { warn "build_gmb_cube failed — aborting (no publish)"; exit 1; }
ok "cube rebuilt"

# 5) publish
if [ "$PUSH" = 1 ]; then
  step "publishing"
  if ! git diff --quiet -- data_gmb_tab.json data_gmb_insights.json data_reviews.json data_gmb_review_cat.json 2>/dev/null; then
    git add data_gmb_tab.json data_gmb_insights.json data_reviews.json data_gmb_review_cat.json 2>/dev/null
    git commit -q -m "GMB tab: daily data refresh ($(date +%Y-%m-%d))" && git push -q origin main && ok "pushed to main"
  else
    ok "no data changes — nothing to publish"
  fi
else
  ok "built locally (--no-push); review then: git add data_gmb_tab.json && git commit && git push"
fi
