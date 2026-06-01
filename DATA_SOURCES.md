# Dashboard Data Sources

This document records **what data comes from where** for every metric in the dashboard.
Update it each time a new week is added.

---

## 1. Primary data pipeline (normal flow)

```
Redshift (allo_prod)
  └─ fetch_bookings.py      → /tmp/bookings_full.csv
       └─ rebuild_data.py   → data.json   (all sections below)
```

**When to use**: whenever AWS SSO (`redshift-data` profile) is available and the
Redshift query returns correct numbers.

**Known issue (as of 2026-06-01)**: `fetch_bookings.py` overcounts offline
appointments (~3×) because `allo_health.locations` contains both physical clinic
IDs and virtual/online consultation room IDs, and the query doesn't filter by
`consultation_type`. Fix: add `AND a.consultation_type = 'offline'` (or
equivalent column) to the WHERE clause before using `rebuild_data.py` again.

---

## 2. data.json — field-by-field sources

### Top-level
| Field | Source |
|-------|--------|
| `weeks` | Derived from Redshift booking schedule dates (Mon–Sun weeks) |
| `week_labels` | Computed: `"{Mon DD MMM} - {Sun DD MMM}"` |
| `categories` | Hard-coded: STI, ED+, PE+, ED+PE+, NSSD, oth |
| `channels` | Hard-coded: GMB, Google, Practo, Organic, Meta, Others |

### `{scope}.weekly_funnel` (scope = all / offline / online)
| Field | Normal source (Redshift) | Manual fallback (used for 2026-05-25) |
|-------|--------------------------|---------------------------------------|
| `calls_done` | Redshift: COUNT WHERE status=COMPLETED, scheduled in week | **L0 sheet** (rows 13-15) |
| `gross` | Redshift: COMPLETED + NO_SHOW | Scaled from prev week by `calls/prev_calls` ratio |
| `slot_booked` | Redshift: all statuses booked in week | Scaled from prev week |
| `no_show` | Redshift: COUNT WHERE status=NO_SHOW | Derived: `gross − calls_done` |
| `rescheduled` | Redshift: COUNT WHERE status=RESCHEDULED | Derived: `slot_booked − gross` |
| `new_bookings` | Redshift: COMPLETED + NO_SHOW where CREATE_DT in week | L0 sheet (rows 8-10) scaled by booking ratio |
| `b2d_pct` | Computed: `calls_done / gross × 100` | Same computation |
| `ns_pct` | Computed: `no_show / gross × 100` | Same computation |

**L0 sheet**: `1jyyFYpd7gfYyAQ3U7E56c7OA3OuQQAVgJrAGyQr90XM`
Tab: (default/first tab)

### `{scope}.weekly_total.by_cat` (category breakdown)
| Field | Normal source | Manual fallback |
|-------|---------------|-----------------|
| `STI` | Redshift: encounter_tags where tag_type='sti', status=COMPLETED | **L0 sheet** (rows 21-23 for offline, 22=online, 21=all) |
| `ED+`, `PE+`, `ED+PE+`, `NSSD`, `oth` | Redshift: encounter_tags by type | Previous-week proportions applied to SH total (L0 sheet rows 18-20) |

### `{scope}.weekly_channel`
| Field | Normal source | Manual fallback |
|-------|---------------|-----------------|
| `GMB.calls_done` | Redshift: Source final starts with "gmb" | **L0 sheet** (rows 100-102 for GMB+Google combined) minus Google standalone (rows 175-177) |
| `Google.calls_done` | Redshift: Source final starts with "google" | **L0 sheet** rows 175-177 |
| `Practo/Organic/Meta/Others.calls_done` | Redshift: by source mapping | Proportionally scaled from prev week using remaining calls |
| All funnel fields (gross, slot_booked, etc.) | Redshift | Scaled from prev week by per-channel calls ratio |

### `{scope}.weekly_city` (only in all + offline scopes)
| Field | Normal source | Manual fallback (used for 2026-05-25) |
|-------|---------------|---------------------------------------|
| `calls_done`, `gross`, `slot_booked` | Redshift: grouped by `loc.city`, scaled by calls | **Booking & Leads trend summary sheet** col 20 (W-1 = newest week), aggregated to city level, then calls_done scaled by `city_bk / total_bk × OFFLINE_CALLS` |
| `no_show`, `rescheduled`, `b2d_pct`, `ns_pct` | Redshift | Derived from calls_done / gross |
| Category breakdown (STI, ED+, etc.) | Redshift | Scaled from previous week's per-city proportions |

**Booking & Leads trend summary sheet**: `1bZWGVKu6b4EFPDt3aKHn21gYjdhN1aT1-LT60BFe8g0`
Tab: "Booking and Leads trend summary"
Column layout (0-indexed, row 1 = dates, W-1 = col 4):
```
Cols 0-3  : City | (blank) | Clinic | Doctor
Cols 4-10 : [Section 1] W-1 through W-7  (dates in row 1)
Cols 11-17: [Section 2] W-1 through W-7
Cols 20-26: SC Offline Booked All  ← city-level and clinic-level booking counts
Cols 27-33: GMB + Google leads     ← used by overview.html / diagnostic.html
Cols 34+  : Older date range (different section, do NOT read for current-week GMB)
Col 44    : Practo Leads start
```
Row structure (per data row):
- Col 1 or 0 = City name
- Col 2 = Clinic locality
- Col 3 = Doctor name
- Rows with Clinic = "All" / "ALL" = city-level aggregates (skip for per-clinic)
- Rows with Doctor = "All" = clinic-level aggregates (or use individual doctor rows and sum)
- ROI cities: individual city rows under "ROI" city header

### `{scope}.weekly_clinic` (only in all + offline scopes)
| Field | Normal source | Manual fallback (used for 2026-05-25) |
|-------|---------------|---------------------------------------|
| `calls_done`, `gross` | Redshift: grouped by `city_locality` | **Same sheet as city** (col 20), per-doctor rows summed per clinic, then scaled so `sum(clinic.calls_done) = city.calls_done` |
| Category breakdown | Redshift | Scaled from previous week's per-clinic proportions |

Clinic key format: `"{city}_{locality}"` (e.g. `"Bangalore_Indiranagar"`)

Special entries in `all` scope only:
- `Practo Online_Practo Online`: online Practo consultations (tiny volume, ~1 call/week)
- `_Online`: other online consultations with no city tag (scaled from prev week)

---

## 3. Sheet data used directly in HTML pages (not via data.json)

These are fetched live by the browser from Google Sheets gviz CSV endpoint.

### overview.html

| Variable | Sheet | Tab | Columns | Used for |
|----------|-------|-----|---------|----------|
| `GMB_LEADS_BY_CITY` | `1bZWGVKu6b4EFPDt3aKHn21gYjdhN1aT1-LT60BFe8g0` | Booking and Leads trend summary | Cols 27-33 (GMB+Google leads, W-1→W-7) | "Total Leads" / GMB trend chart |
| `AVAIL_DATA` | Same | Same | Cols 4-10 (availability), 20-26 (all bookings) | Availability % and booking trend per city/clinic |
| `TOTAL_LEADS_WK` | `1jyyFYpd7gfYyAQ3U7E56c7OA3OuQQAVgJrAGyQr90XM` | L0 | Row 100 col 2 (GMB+Google calls, W-1) | Top-level "Total Leads" override |

Weeks covered by sheet fetch: `OV_SHEET_WEEKS` in overview.html — must match the
**current sheet's W-1 position** (newest date at col 4/20/27).  
**Current value** (updated 2026-06-01): `['2026-05-25','2026-05-18',...,'2026-04-13']`
(7 entries covering 7 GMB columns 27-33; Apr 6-12 dropped when May 25-31 was added)

### diagnostic.html

| Variable | Sheet | Tab | Columns | Used for |
|----------|-------|-----|---------|----------|
| `SDATA` (gmbLeads) | `1bZWGVKu6b4EFPDt3aKHn21gYjdhN1aT1-LT60BFe8g0` | Booking and Leads trend summary | Cols 27-33 (array index 0-6) | Per-city GMB leads in clinic table |
| `SDATA` (allBk) | Same | Same | Cols 20-26 | "All bookings" column in clinic table |
| `SDATA` (avail) | Same | Same | Cols 4-10 | Availability % in clinic table |
| `PRACTO_DATA` | Same | `RD_Practo_Leads` | Parsed by city/clinic | Practo leads column |
| `L0_DATA` | `1jyyFYpd7gfYyAQ3U7E56c7OA3OuQQAVgJrAGyQr90XM` | L0 | Multiple rows | Overall funnel KPIs at top |

`WEEKS` array in diagnostic.html: 8 entries (newest first), array index = sheet column
offset from the base column (e.g. gmbLeads[0] = col 27, gmbLeads[6] = col 33).
The 8th entry (Apr 6-12) will show zero for sheet-sourced metrics since arrays are length-7.

### efficiency.html

Efficiency page reads `data.json` for B2D% and funnel metrics.
It also fetches the L0 sheet (`1jyyFYpd7gfYyAQ3U7E56c7OA3OuQQAVgJrAGyQr90XM`)
for `calls_done_l0` overrides (channel-level calls from the sheet).
No hard-coded week lists — uses dynamic week discovery from `data.json`.

`L0_CACHE_KEY = 'allo_eff_l0_v5'` (bumped 2026-06-01)  
`L0_WEEK_COLS = [2,3,4,5,6,7,8]` (col 2 = W-1, 25 May; same update rule as diagnostic.html)  
`JSON_WEEK_KEYS = ['2026-05-25',...]` — Monday start-of-week dates matching data.json keys (newest first)

**Funnel Break Analyzer** now shows W-1 / W-2 / W-3 side-by-side per channel card.
Changing the week selector shifts the entire 3-column window.

### weekly-report.html

Auto-generated weekly demand report. Reads only `data.json` (no sheet fetch required).
Optionally fetches L0 sheet for richer context (non-blocking, degrades gracefully).

- Week selector: choose any week in data.json history
- Sections: KPI cards, executive summary, channel bookings, offline/online funnels,
  city table, clinic movers, channel calls table, root-cause matrix, recommendations
- `L0_CACHE_KEY = 'allo_report_l0_v1'`

### diagnostic.html

| Variable | Sheet | Columns | Used for |
|----------|-------|---------|----------|
| `L0_DIAG` (ad-platform signals) | L0 sheet | `L0_WEEK_COLS` (7 columns, most-recent first) | Impressions, clicks, CTR, spends panels |
| `SDATA` (gmbLeads, allBk, avail) | Booking & Leads trend summary | Same as diagnostic.html above | City/clinic table |

`L0_WEEK_COLS` in diagnostic.html: must match current W-1 column in L0 sheet.
**Current value** (updated 2026-06-01): `[2, 3, 4, 5, 6, 7, 8]` (col 2 = W-1 = 25 May)

When a new week is added to L0 sheet, shift all values left by 1: `[2→1...]` becomes `[1, 2, 3, 4, 5, 6, 7]` etc.
Actually: new week is prepended at col 2, old col 2 shifts to col 3, so update by shifting array up by 1:
`[2,3,4,5,6,7,8]` → next week becomes `[2,3,4,5,6,7,8]` (same values if new week inserts at same position)
→ Verify by checking L0 row 1 (date header) — col 2 should be the newest Sunday date.

---

## 4. Week-addition checklist

When adding a new week (e.g. "June 1-7"):

### A. Get exact numbers from L0 sheet
Sheet: `1jyyFYpd7gfYyAQ3U7E56c7OA3OuQQAVgJrAGyQr90XM`

| Row | Field |
|-----|-------|
| 8 | All bookings total |
| 9 | Online bookings |
| 10 | Offline bookings |
| 13 | All calls done |
| 14 | Online calls done |
| 15 | Offline calls done |
| 18 | All SH done (ED+/PE+/ED+PE+/NSSD/oth combined) |
| 19 | Online SH done |
| 20 | Offline SH done |
| 21 | All STI done |
| 22 | Online STI done |
| 23 | Offline STI done |
| 100 | GMB+Google calls total |
| 101 | GMB+Google calls online |
| 102 | GMB+Google calls offline |
| 175 | Google Search calls total |
| 176 | Google Search calls online |
| 177 | Google Search calls offline |

Then: `GMB_total = row100 − row175`, `GMB_offline = row102 − row177`

### B. Get city + clinic data from Booking & Leads trend summary sheet
Sheet: `1bZWGVKu6b4EFPDt3aKHn21gYjdhN1aT1-LT60BFe8g0`
Tab: "Booking and Leads trend summary"
- After sheet is updated with new week: **all column offsets shift by +1**
  (new week is prepended at W-1, everything moves right)
- Col 20 = new W-1 for "SC Offline Booked All" → per-clinic booking counts
- Col 27 = new W-1 for GMB leads
- Update `OV_SHEET_WEEKS` in `overview.html` to drop oldest week, prepend new week key
- `WEEKS` in `diagnostic.html` already handles 8 entries; add new entry at index 0

### C. Run the add_new_week.py script
Update hardcoded values in `add_new_week.py` from L0 sheet, then run it.
This handles funnel, weekly_total, channel breakdown.

### D. Run populate_city_may25.py (or equivalent)
Update `SHEET_BOOKINGS` dict with per-city values from col 20 of the Booking & Leads
sheet, then run. This populates `weekly_city`.

### E. Run populate_clinic_may25.py (or equivalent)
Update `CLINIC_BK` dict with per-clinic values (aggregate per-doctor rows by clinic),
then run. This populates `weekly_clinic`.

### F. Derived Madhapur (or any "missing" clinic)
If a clinic appears in data.json but not in the sheet:
`missing_clinic_bk = city_All_bk − sum(visible_clinic_bk_for_that_city)`

---

## 5. Sheet gviz URL pattern

```
https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={TAB_NAME_URL_ENCODED}
```

| Sheet | ID |
|-------|----|
| L0 (calls/bookings/channel) | `1jyyFYpd7gfYyAQ3U7E56c7OA3OuQQAVgJrAGyQr90XM` |
| Booking & Leads trend summary | `1bZWGVKu6b4EFPDt3aKHn21gYjdhN1aT1-LT60BFe8g0` |

> **CORS note**: Browser fetches of these sheets will fail with 401 / CORS errors
> in some environments. All page JS uses `safeFetch` wrappers so failures degrade
> gracefully rather than crashing the page.

---

*Last updated: 2026-06-01 (v3) — weekly-report.html: "New Bookings" KPI, exec summary, and KEY FINDING banner now use `L0.overall.bookings[wi]` (row 8 of L0 sheet, the team-tracked value ≈ 1652) instead of data.json `new_bookings` (Redshift COMPLETED+NO_SHOW, a different metric ≈ 1970). 8wk avg for bookings also computed from L0 array when available. `add_new_week.py` corrected: `ALL_BOOKINGS = 1652` (was 1794). `L0_CACHE_KEY = 'allo_report_l0_v3'` unchanged.*

---

## 6. diagnosis.json — sheet-exact weekly RCA (Diagnosis page)

```
demand tracker .xlsx (Book2Done_Raw_Data, Leads_Raw)  +  Redshift roster_slots
   └─ build_diagnosis.py  → diagnosis.json  → diagnosis.html
```

Rebuilt on the **tracker sheet's own L0 logic** (reconciles to the sheet to the row):
- **Bookings** = `Book2Done_Raw_Data` where `apt_create_dt` in week **AND `phone_rank = 1`** (new-patient dedup, no status filter)
- **Channel** = `Source final` (sheet's phone-line waterfall: Practo → Google Ad-Mapping → FB lines → GMB → Organic)
- **Online/Offline** = `locality = 'Online'`; **Category** = `diag_cat`
- **Leads** = `Leads_Raw` by `created_on_date`, channel via `Source Final` (rolling ~6-wk window → 5-wk baseline)
- **Availability** (active-days) = Redshift `roster_slots` (≥60 min realized/bookable SC) — the only non-sheet input

Every clinic is classified **Availability / L2B Conversion / Growing / Stable** via the
weekend-weighted demand×availability framework, and bucketed New / Maturing / Mature
(≥25 bookings/wk & ≥8 wks data). Rebuild: `python3 build_diagnosis.py --sheet-xlsx <export>.xlsx --w6-start <Mon>`.
