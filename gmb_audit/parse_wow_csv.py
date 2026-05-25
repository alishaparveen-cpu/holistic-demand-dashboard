"""
Parse `Clinic Wise WoW - GMB_ Clinic Wise WTD Tracker.csv` into a clean JSON
for the dashboard. Source: founder's weekly tracker, online bookings only.

Output: /workspace/holistic-demand-dashboard/wow_data.json
"""

import csv
import json
from datetime import datetime
from pathlib import Path

CSV_PATH = Path(__file__).parent / "Clinic Wise WoW - GMB_ Clinic Wise WTD Tracker.csv"
OUT_PATH = Path(__file__).parent.parent / "wow_data.json"

# CSV layout (1-indexed mental model, 0-indexed in code):
# rows[13] = week-end labels (col 6 onward),  rows[14] = week-start labels
# col 6 = current partial week, col 7 = last full week, ..., col 18 = oldest
# Each "metric" lives on a specific row. Numeric values in cols 6..18.

# Map metric → row index. Names match the founder's sheet.
METRIC_ROWS = {
    "all_unique_bookings":   25,   # Headline online bookings
    "google_gmb_clicks":     30,   # Google (GMB) — web clicks from GMB profile
    "google_listing_clicks": 31,
    "walk_in":               32,
    "pc_inbound":            33,
    "google_paid":           35,
    "gmb_calls":             37,   # Calls from GMB tracking number
    "gmb_old_nos":           38,
    "gmb_bangalore":         39,
    "gmb_mumbai":            40,
    "gmb_hyderabad":         41,
    "gmb_pune":              42,
    "gmb_chennai":           43,
    "gmb_t2":                44,
    "other_sources":         46,
    # Channel breakdown of TOTAL bookings (rows 119-127)
    "practo":                119,
    "fb":                    120,
    "google_search":         121,
    "organic":               124,
    "whatsapp":              125,
    "organic_wa":            126,
    "justdial":              127,
    # New bookings (first-time patients)
    "new_bookings":          129,
    "new_fb":                140,
    "new_google":            141,
    "new_organic":           142,
    "new_others":            144,
    # Funnel
    "calls_done":            148,
    "calls_done_sti":        197,
    "calls_done_non_sti":    237,
    "slot_booked":           239,
    "rescheduled":           240,
    "gross_bookings":        242,
    "completed":             243,
    "no_show":               245,
}

# Channels considered "online" (for spike decomposition contribution)
ONLINE_CHANNELS = ["fb","google_search","organic","whatsapp","organic_wa","practo","justdial"]


def num(s):
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def parse_date(s, year=2026):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(f"{s} {year}", "%d %b %Y").date().isoformat()
    except ValueError:
        return None


def main():
    rows = list(csv.reader(open(CSV_PATH)))

    # Week metadata: cols 6..18
    weeks = []
    for col in range(6, 19):
        end_s = rows[13][col] if len(rows[13]) > col else ""
        start_s = rows[14][col] if len(rows[14]) > col else ""
        weeks.append({
            "col": col,
            "start": parse_date(start_s),
            "end":   parse_date(end_s),
            "label": f"{(start_s or '').strip()} → {(end_s or '').strip()}",
        })

    # Metrics
    metrics = {}
    for name, rownum in METRIC_ROWS.items():
        if rownum >= len(rows):
            continue
        r = rows[rownum]
        metrics[name] = [num(r[w["col"]]) if len(r) > w["col"] else 0.0 for w in weeks]

    out = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source": "Clinic Wise WoW - GMB_ Clinic Wise WTD Tracker.csv",
        "scope": "Online bookings only (founder's weekly tracker)",
        "weeks": weeks,
        "metrics": metrics,
        "online_channels": ONLINE_CHANNELS,
    }

    OUT_PATH.write_text(json.dumps(out, separators=(",", ":")))
    print(f"✓ wrote {OUT_PATH} ({OUT_PATH.stat().st_size:,} bytes)")
    print(f"  {len(weeks)} weeks · {len(metrics)} metrics")

    # Quick sanity: spike week (4-10 May) total
    spike_idx = next(i for i, w in enumerate(weeks) if w["start"] == "2026-05-04")
    print(f"  spike week ({weeks[spike_idx]['label']}): "
          f"All Unique Bookings = {metrics['all_unique_bookings'][spike_idx]:.0f}")


if __name__ == "__main__":
    main()
