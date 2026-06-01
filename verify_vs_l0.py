"""
verify_vs_l0.py — After running fetch_bookings.py + rebuild_data.py,
compare key metrics in data.json against the live L0 Google Sheet.

Run: python3 verify_vs_l0.py

Prints a table with ✓ (match within 3%) or ✗ (mismatch) per metric per week.
"""

import csv, json, io, urllib.request

L0_SHEET_ID  = "1jyyFYpd7gfYyAQ3U7E56c7OA3OuQQAVgJrAGyQr90XM"
L0_URL       = f"https://docs.google.com/spreadsheets/d/{L0_SHEET_ID}/gviz/tq?tqx=out:csv&sheet=L0"
DATA_JSON    = "/Users/alishaparveen/holistic-demand-dashboard/data.json"
TOLERANCE    = 0.05   # 5% tolerance

month_map = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}

def parse_week(s):
    s = s.strip()
    parts = s.split()
    if len(parts) < 2:
        return None
    mon = month_map.get(parts[1][:3])
    return f"2026-{mon}-{parts[0].zfill(2)}" if mon else None

def nv(s):
    try:
        return int(float((s or "").strip().replace(",", "").replace("%", "")))
    except Exception:
        return None


def main():
    print("→ Fetching L0 sheet…")
    try:
        with urllib.request.urlopen(L0_URL, timeout=20) as resp:
            text = resp.read().decode("utf-8")
    except Exception as e:
        print(f"  ✗ Could not fetch L0: {e}")
        return

    raw = list(csv.reader(io.StringIO(text)))

    # Build col → week_key mapping from start-date row (index 2)
    col_week = {}
    for c in range(1, 20):
        if c >= len(raw[2]):
            break
        wk = parse_week(raw[2][c])
        if wk:
            col_week[c] = wk

    print(f"  L0 sheet covers {len(col_week)} weeks: {list(col_week.values())[0]} … {list(col_week.values())[-1]}")

    print("→ Loading data.json…")
    with open(DATA_JSON) as f:
        d = json.load(f)

    labels = d.get("week_labels", {})

    # Metrics to compare
    # (label, l0_row, scope, field_in_funnel, l0_is_float)
    checks = [
        ("calls_done (all)",     13, "all",     "calls_done", False),
        ("calls_done (offline)", 15, "offline",  "calls_done", False),
        ("calls_done (online)",  14, "online",   "calls_done", False),
        ("gross/bk (all)",        8, "all",      "gross",      False),
        ("gross/bk (offline)",   10, "offline",  "gross",      False),
        ("gross/bk (online)",     9, "online",   "gross",      False),
    ]

    print()
    header = f"{'Week':<24}" + "".join(f"  {c[0]:<22}" for c in checks)
    print(header)
    print("-" * (24 + 24 * len(checks)))

    ok_total = fail_total = 0

    for c, wk in sorted(col_week.items()):
        if wk not in d.get("weeks", []):
            continue
        lbl = labels.get(wk, wk)
        row_str = f"{lbl:<24}"

        for (metric_lbl, l0_row, scope, field, _) in checks:
            l0_val = nv(raw[l0_row][c] if c < len(raw[l0_row]) else "")
            json_val = d.get(scope, {}).get("weekly_funnel", {}).get(wk, {}).get(field)

            if l0_val is None or json_val is None:
                symbol = "  —"
                row_str += f"  {'—':<22}"
                continue

            pct_diff = abs(l0_val - json_val) / l0_val if l0_val else 0
            if pct_diff <= TOLERANCE:
                symbol = "✓"
                ok_total += 1
            else:
                symbol = "✗"
                fail_total += 1

            row_str += f"  {symbol} {json_val:>6} vs {l0_val:>6} ({(json_val-l0_val):+d})"

        print(row_str)

    print()
    print(f"Summary: {ok_total} ✓  {fail_total} ✗  (tolerance ±{TOLERANCE*100:.0f}%)")
    if fail_total > 0:
        print("→ Failures likely mean consultation_type filter needs adjustment.")
        print("  Check: SELECT DISTINCT consultation_type FROM allo_consultations.appointments LIMIT 20;")


if __name__ == "__main__":
    main()
