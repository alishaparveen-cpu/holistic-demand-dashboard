"""
populate_city_may25.py — Populate weekly_city for 2026-05-25 using real per-city
booking numbers from the Booking and Leads trend summary sheet (col 20 = W-1).

City booking totals (col 20, date 31/05/2026 = May 25-31 week):
  Bangalore    = 356  (from "Bangalore, All, All" row)
  Mumbai       = 241  (from "Mumbai, All, All" row)
  Navi Mumbai  =  52  (36 Kharghar + 4 Vashi + 12 Panvel — no All row)
  Hyderabad    = 201  (from "Hyderabad, All, All" row)
  Chennai      = 115  (from "Chennai, All, All" row)
  Pune         = 221  (from "Pune, All, All" row)
  ROI cities each taken individually (sum = 304, matches ROI All row)
"""

import json

DATA_JSON = "/Users/alishaparveen/holistic-demand-dashboard/data.json"
NEW_WK    = "2026-05-25"
PREV_WK   = "2026-05-18"

# ── Real booking numbers from sheet (col 20, W-1 = May 25-31) ───────────────
SHEET_BOOKINGS = {
    "Bangalore":    356,
    "Mumbai":       241,
    "Navi Mumbai":   52,   # Kharghar 36 + Vashi 4 + Panvel 12
    "Hyderabad":    201,
    "Chennai":      115,
    "Pune":         221,
    # ROI individual cities (no city-level "All" row):
    "Mysuru":        39,
    "Nagpur":        54,
    "Nashik":         3,
    "Ranchi":        20,
    "Mangaluru":     16,
    "Hubli":         13,
    "Aurangabad":     7,
    "Jaipur":        26,
    "Coimbatore":    63,
    "Surat":         15,
    "Visakhapatnam": 15,
    "Ahmedabad":     12,
    "Gandhinagar":    8,
    "Bhopal":        13,
}

CATEGORIES = ["STI", "ED+", "PE+", "ED+PE+", "NSSD", "oth"]

# ── Load data.json ────────────────────────────────────────────────────────────
with open(DATA_JSON) as f:
    d = json.load(f)

# Offline funnel for new week (exact L0 numbers already injected)
offline_fn  = d["offline"]["weekly_funnel"][NEW_WK]
TOTAL_CALLS = offline_fn["calls_done"]   # 874
TOTAL_GROSS = offline_fn["gross"]        # 1333
TOTAL_SLOT  = offline_fn["slot_booked"]  # 1776

total_bk = sum(SHEET_BOOKINGS.values())  # 1490

prev_cities = d["offline"]["weekly_city"][PREV_WK]

def scale(v, new_calls, prev_calls):
    if prev_calls == 0:
        return 0
    return max(0, round(v * new_calls / prev_calls))

# ── Build per-city entries ────────────────────────────────────────────────────
city_entries = {}
for city, city_bk in SHEET_BOOKINGS.items():
    city_calls = round(city_bk / total_bk * TOTAL_CALLS)
    city_gross = round(city_bk / total_bk * TOTAL_GROSS)
    city_slot  = round(city_bk / total_bk * TOTAL_SLOT)
    city_ns    = max(0, city_gross - city_calls)
    city_resc  = max(0, city_slot  - city_gross)
    b2d = round(city_calls / city_gross * 100, 1) if city_gross else 0.0
    ns  = round(city_ns   / city_gross * 100, 1) if city_gross else 0.0

    # Category breakdown: scale from previous week's proportions
    prev = prev_cities.get(city, {})
    prev_calls = prev.get("calls_done", 0)
    cats = {}
    if prev_calls > 0:
        for cat in CATEGORIES:
            cats[cat] = scale(prev.get(cat, 0), city_calls, prev_calls)
    else:
        # Fall back to overall offline proportions for cities with no prev data
        prev_total = d["offline"]["weekly_total"][PREV_WK]
        prev_t_calls = prev_total["total"]
        for cat in CATEGORIES:
            cats[cat] = scale(prev_total["by_cat"].get(cat, 0), city_calls, prev_t_calls)
    # Reconcile sum → city_calls
    cat_sum = sum(cats.values())
    if cat_sum != city_calls:
        cats["oth"] = max(0, cats["oth"] + (city_calls - cat_sum))

    city_entries[city] = {
        **cats,
        "total":       city_calls,
        "slot_booked": city_slot,
        "gross":       city_gross,
        "calls_done":  city_calls,
        "no_show":     city_ns,
        "rescheduled": city_resc,
        "b2d_pct":     b2d,
        "ns_pct":      ns,
    }

# ── Fix rounding so calls_done sum == TOTAL_CALLS ────────────────────────────
allocated = sum(v["calls_done"] for v in city_entries.values())
diff = TOTAL_CALLS - allocated
if diff != 0:
    # Apply adjustment to the largest city (Bangalore)
    city_entries["Bangalore"]["calls_done"] += diff
    city_entries["Bangalore"]["total"]      += diff
    city_entries["Bangalore"]["oth"]         = max(0, city_entries["Bangalore"]["oth"] + diff)
    calls = city_entries["Bangalore"]["calls_done"]
    gross = city_entries["Bangalore"]["gross"]
    city_entries["Bangalore"]["b2d_pct"] = round(calls / gross * 100, 1) if gross else 0.0
    city_entries["Bangalore"]["ns_pct"]  = round(city_entries["Bangalore"]["no_show"] / gross * 100, 1) if gross else 0.0
    print(f"  Rounding adj {diff:+d} applied to Bangalore")

# ── Write offline scope ───────────────────────────────────────────────────────
d["offline"]["weekly_city"][NEW_WK] = city_entries

# ── Write all scope (same cities + Practo Online) ────────────────────────────
all_city_entries = dict(city_entries)
prev_po = d["all"]["weekly_city"][PREV_WK].get("Practo Online", {})
prev_po_calls = prev_po.get("calls_done", 0)
if prev_po_calls > 0:
    all_calls_prev = d["all"]["weekly_funnel"][PREV_WK]["calls_done"]   # 1471
    all_calls_new  = d["all"]["weekly_funnel"][NEW_WK]["calls_done"]    # 1361
    po_calls = max(0, round(prev_po_calls * all_calls_new / all_calls_prev))
    po_cats  = {cat: scale(prev_po.get(cat, 0), po_calls, prev_po_calls) for cat in CATEGORIES}
    po_sum   = sum(po_cats.values())
    if po_sum != po_calls:
        po_cats["oth"] = max(0, po_cats["oth"] + (po_calls - po_sum))
else:
    po_calls = 0
    po_cats  = {cat: 0 for cat in CATEGORIES}

all_city_entries["Practo Online"] = {
    **po_cats,
    "total":       po_calls,
    "slot_booked": po_calls,
    "gross":       po_calls,
    "calls_done":  po_calls,
    "no_show":     0,
    "rescheduled": 0,
    "b2d_pct":     100.0 if po_calls > 0 else 0.0,
    "ns_pct":      0.0,
}
d["all"]["weekly_city"][NEW_WK] = all_city_entries

# ── Write data.json ───────────────────────────────────────────────────────────
with open(DATA_JSON, "w") as f:
    json.dump(d, f, separators=(",", ":"))

# ── Sanity output ─────────────────────────────────────────────────────────────
print(f"✓ Wrote {DATA_JSON}")
print(f"\nCity breakdown for {NEW_WK} (offline):")
print(f"  {'City':<16} {'Sheet Bk':>8}  {'calls':>6}  {'gross':>6}  {'b2d%':>6}")
for city, v in sorted(city_entries.items()):
    print(f"  {city:<16} {SHEET_BOOKINGS[city]:>8}  {v['calls_done']:>6}  {v['gross']:>6}  {v['b2d_pct']:>6}%")
total_calls_check = sum(v["calls_done"] for v in city_entries.values())
print(f"  {'TOTAL':<16} {total_bk:>8}  {total_calls_check:>6}  (expected {TOTAL_CALLS})")
print(f"\n{'OK' if total_calls_check == TOTAL_CALLS else 'MISMATCH'}: city calls_done sum = {total_calls_check}")
