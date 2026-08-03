# Competition Intelligence — data & pipeline

This folder holds the API competition data and the builder behind the
**Competition Intelligence** view (`comp-intelligence.html` → `data_competition.json`).

## Data files (API pulls)
| File | Source | What it is |
|---|---|---|
| `data_serp_competitors.tsv` | Redshift `allo_analytics.serp_analyses` (SERP grid) | Per-clinic local-pack competitors, appearances, our avg rank |
| `data_serp_dfs.json` | DataForSEO Maps crawl | Single-point crawl: competitor name, GMB category, reviews, rating, distance, Place ID |
| `data_serp_pathy.tsv`, `data_serp_pathy_v2.tsv`, `data_serp_sh_pathy.tsv` | Manual/verified | Business-type (pathy) + rival/non-rival labels keyed by name/place_id |
| `data_gmb_comp.json` | GMB insights | Per-clinic searches/calls/website/directions (demand proxy) |
| `data_campaign_compose.json` | Ads/funnel | City funnel economics (spend, leads, bookings) |

## Pipeline
1. `pull_serp_competitors.py` → `data_serp_competitors.tsv` (Redshift)
2. `pull_dfs_competition.py` → `data_serp_dfs.json` (DataForSEO)
3. `pull_gmb_comp.py` → `data_gmb_comp.json`
4. `build_competition_cube.py` → **`data_competition.json`** (national / city / clinic rollups + rivals + verdicts)

## The relevance fix (2026-07)
The map-pack scan returns any business that ranks locally, so language schools,
spas, IVF centres and giant general hospitals were being stored as "rivals" and
inflating the top-rival review count (e.g. Electronic City showed a 27,100-review
general hospital as its rival). Three changes in `build_competition_cube.py`:

1. **`cat_relevant()` reordered** — an MH signal (psychiatr / psycholog / counsel /
   therap / mental / rehab …) is now tested **before** the drop list, so
   "psychiatric **hospital**" stays a rival while a generic hospital does not.
2. **Drop list extended** — generic hospital / multispeciality / fertility / IVF /
   dental / skin / spa / physiotherapy / language-school / career-guidance are now
   explicitly non-rivals. A hard-drop set guards words that overlap a signal
   (physio-**therapy**, **career** counselling).
3. **Stored competitor list filtered** — every `rel == False` business is dropped
   from the saved list in all three build paths, so the dashboard table shows only
   genuine mental-health competitors.

Impact: 30 of 83 MH clinics had inflated rival counts corrected; 0 non-MH
businesses remain in any stored competitor list; clinic count and the vast majority
of verdicts unchanged (surgical fix).

To refresh: run the three `pull_*.py` (needs AWS/Redshift + DataForSEO creds), then
`python3 build_competition_cube.py`.
