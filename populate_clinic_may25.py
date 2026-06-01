"""
populate_clinic_may25.py
========================
Populate weekly_clinic[2026-05-25] from real per-clinic booking values
in the Booking and Leads trend summary sheet.

Source sheet: 1bZWGVKu6b4EFPDt3aKHn21gYjdhN1aT1-LT60BFe8g0
Tab: "Booking and Leads trend summary"
Column used: col 20 (0-indexed) = "SC Offline Booked All Booked During the Week"
Date header row (row 1): col 20 = 31/05/2026 = W-1 (week of May 25-31)

Per-doctor rows are aggregated per clinic (city_locality key format).
Hyderabad_Madhapur is derived as (Hyderabad_All - sum_of_visible_hyd_clinics).

Calls_done per clinic are scaled so that each city's clinic calls_done sum
equals the city's calls_done already stored in weekly_city[2026-05-25].
"""

import json

DATA_JSON = "/Users/alishaparveen/holistic-demand-dashboard/data.json"
NEW_WK    = "2026-05-25"
PREV_WK   = "2026-05-18"

# ── Sheet bookings per clinic (col 20, W-1 = 31/05/2026)
# Format: "City_Locality": bookings  (sum of all doctor rows at that clinic)
# Source: Booking and Leads trend summary sheet, fetched 2026-06-01
# -----------------------------------------------------------------
# Bangalore (sheet "Bangalore, All" = 356; visible clinics sum = 364)
# Mumbai    (sheet "Mumbai, All"     = 241; visible clinics sum = 247)
# Chennai   (sheet "Chennai, All"    = 115; visible clinics sum = 127)
# Pune      (sheet "Pune, All"       = 221; visible clinics sum = 226)
# Hyderabad (sheet "Hyderabad, All"  = 201; visible clinics sum = 188 → Madhapur = 13)
# Navi Mumbai (no city-level All row; sum of 3 clinics = 52)
# -----------------------------------------------------------------
CLINIC_BK = {
    # ── Bangalore ──────────────────────────────────────────
    "Bangalore_Indiranagar":    49,   # Dr. Shraddha 0 + Dr. Basava 17 + Dr. Adithya 32
    "Bangalore_Koramangala":    27,
    "Bangalore_HSR Layout":     40,
    "Bangalore_Whitefield":     28,   # Dr. Basava 13 + Dr. Megha 15
    "Bangalore_Electronic City":29,
    "Bangalore_Bellandur":      24,
    "Bangalore_Jayanagar":      60,
    "Bangalore_KR Puram":       28,
    "Bangalore_RT Nagar":        3,
    "Bangalore_Sahakara Nagar": 36,
    "Bangalore_Vijayanagar":    19,
    "Bangalore_Arekere":         9,
    "Bangalore_Kengeri":        12,
    # ── Mumbai ─────────────────────────────────────────────
    "Mumbai_Andheri East":      53,   # Dr. Chaitra 29 + Dr. Abhijeet 24
    "Mumbai_Borivali":          44,
    "Mumbai_Dadar":             23,
    "Mumbai_Ghatkopar":         46,   # Dr. Nikunj 46 + Dr. Durganjali 0
    "Mumbai_Kalyan West":       33,
    "Mumbai_Thane":             48,
    # ── Navi Mumbai ────────────────────────────────────────
    "Navi Mumbai_Kharghar":     36,
    "Navi Mumbai_Vashi":         4,
    "Navi Mumbai_Panvel":       12,
    # ── Hyderabad ──────────────────────────────────────────
    "Hyderabad_Ameerpet":       45,
    "Hyderabad_Sainikpuri":     23,
    "Hyderabad_Kondapur":       52,   # Dr. Vignan 36 + Dr. Vinya 16
    "Hyderabad_Kukatpally":     27,
    "Hyderabad_Nallagandla":    16,
    "Hyderabad_Narsingi":       25,
    "Hyderabad_Madhapur":       13,   # derived: Hyderabad_All(201) − visible clinics(188)
    # ── Chennai ────────────────────────────────────────────
    "Chennai_Mogappair":        27,   # Dr. Madhumitha 17 + Dr. Neslin 10
    "Chennai_Nungambakkam":     34,
    "Chennai_Tambaram":         14,
    "Chennai_Thoraipakkam":     12,
    "Chennai_Velachery":        40,
    # ── Pune ───────────────────────────────────────────────
    "Pune_Baner":               23,
    "Pune_Chinchwad":           24,
    "Pune_Hadapsar":            42,
    "Pune_Katraj":              19,
    "Pune_Kharadi":             43,
    "Pune_Kothrud":             33,
    "Pune_Wakad":               42,
    # ── ROI cities (one clinic each) ───────────────────────
    "Mysuru_Saraswathipuram":   39,
    "Nagpur_Tatya Tope Nagar":  54,
    "Nashik_Trimurti Chowk":     3,
    "Ranchi_Ashok Nagar":       20,
    "Mangaluru_Falnir Rd":      16,
    "Hubli_Vidya Nagar":        13,
    "Aurangabad_Garkheda":       7,
    "Jaipur_Vaishali Nagar":    26,
    "Coimbatore_Bharathi Nagar":63,
    "Surat_Bhimrad":            15,
    "Visakhapatnam_MVP Colony": 15,
    "Ahmedabad_Paldi":          12,
    "Gandhinagar_Kudasan":       8,
    "Bhopal_Gulmohar":          13,
}

CATEGORIES = ["STI", "ED+", "PE+", "ED+PE+", "NSSD", "oth"]

# ── Load data ──────────────────────────────────────────────────────────────────
with open(DATA_JSON) as f:
    d = json.load(f)

# Already-set city calls_done for the new week (use as authoritative city totals)
city_calls_target = {
    city: v["calls_done"]
    for city, v in d["offline"]["weekly_city"][NEW_WK].items()
}
city_gross_target = {
    city: v["gross"]
    for city, v in d["offline"]["weekly_city"][NEW_WK].items()
}
city_slot_target = {
    city: v["slot_booked"]
    for city, v in d["offline"]["weekly_city"][NEW_WK].items()
}

offline_fn = d["offline"]["weekly_funnel"][NEW_WK]

prev_clinics = d["offline"]["weekly_clinic"][PREV_WK]

def scale(v, new_calls, prev_calls):
    if prev_calls == 0:
        return 0
    return max(0, round(v * new_calls / prev_calls))

# ── Group clinic keys by city ──────────────────────────────────────────────────
from collections import defaultdict
by_city = defaultdict(dict)
for ck, bk in CLINIC_BK.items():
    city = ck.split("_", 1)[0]
    by_city[city][ck] = bk

# ── Build per-clinic entries, keeping city sums consistent ────────────────────
clinic_entries = {}

for city, clinics in by_city.items():
    city_bk_total = sum(clinics.values())
    target_calls  = city_calls_target.get(city, 0)
    target_gross  = city_gross_target.get(city, 0)
    target_slot   = city_slot_target.get(city, 0)

    allocated_calls = 0
    clinic_list = sorted(clinics.keys(), key=lambda k: clinics[k], reverse=True)

    for ck in clinic_list:
        clinic_bk = clinics[ck]
        if city_bk_total == 0:
            c_calls = 0; c_gross = 0; c_slot = 0
        else:
            c_calls = round(clinic_bk / city_bk_total * target_calls)
            c_gross = round(clinic_bk / city_bk_total * target_gross)
            c_slot  = round(clinic_bk / city_bk_total * target_slot)

        c_ns   = max(0, c_gross - c_calls)
        c_resc = max(0, c_slot - c_gross)
        b2d    = round(c_calls / c_gross * 100, 1) if c_gross else 0.0
        ns     = round(c_ns / c_gross * 100, 1) if c_gross else 0.0

        # Category breakdown: scale from previous week proportions
        prev = prev_clinics.get(ck, {})
        prev_calls_prev = prev.get("calls_done", 0)
        cats = {}
        if prev_calls_prev > 0:
            for cat in CATEGORIES:
                cats[cat] = scale(prev.get(cat, 0), c_calls, prev_calls_prev)
        else:
            # Fall back to overall offline proportions
            prev_total = d["offline"]["weekly_total"][PREV_WK]
            prev_t_calls = prev_total["total"]
            for cat in CATEGORIES:
                cats[cat] = scale(prev_total["by_cat"].get(cat, 0), c_calls, prev_t_calls)
        # Reconcile cats sum → c_calls
        cat_sum = sum(cats.values())
        if cat_sum != c_calls:
            cats["oth"] = max(0, cats["oth"] + (c_calls - cat_sum))

        clinic_entries[ck] = {
            **cats,
            "total":       c_calls,
            "slot_booked": c_slot,
            "gross":       c_gross,
            "calls_done":  c_calls,
            "no_show":     c_ns,
            "rescheduled": c_resc,
            "b2d_pct":     b2d,
            "ns_pct":      ns,
        }
        allocated_calls += c_calls

    # Fix rounding: adjust the largest clinic in this city
    diff = target_calls - allocated_calls
    if diff != 0 and clinic_list:
        top_ck = clinic_list[0]
        clinic_entries[top_ck]["calls_done"] += diff
        clinic_entries[top_ck]["total"]      += diff
        clinic_entries[top_ck]["oth"]         = max(0, clinic_entries[top_ck]["oth"] + diff)
        calls = clinic_entries[top_ck]["calls_done"]
        gross = clinic_entries[top_ck]["gross"]
        clinic_entries[top_ck]["b2d_pct"] = round(calls / gross * 100, 1) if gross else 0.0
        clinic_entries[top_ck]["ns_pct"]  = round(clinic_entries[top_ck]["no_show"] / gross * 100, 1) if gross else 0.0

# ── Write offline scope ────────────────────────────────────────────────────────
d["offline"]["weekly_clinic"][NEW_WK] = clinic_entries

# ── Write all scope (same + Practo Online_Practo Online and _Online entries) ──
all_clinic_entries = dict(clinic_entries)
for special_key in ["Practo Online_Practo Online", "_Online"]:
    prev_sp = d["all"]["weekly_clinic"][PREV_WK].get(special_key, {})
    prev_sp_calls = prev_sp.get("calls_done", 0)
    if prev_sp_calls > 0:
        all_calls_prev = d["all"]["weekly_funnel"][PREV_WK]["calls_done"]
        all_calls_new  = d["all"]["weekly_funnel"][NEW_WK]["calls_done"]
        sp_calls = max(0, round(prev_sp_calls * all_calls_new / all_calls_prev))
        sp_cats  = {cat: scale(prev_sp.get(cat, 0), sp_calls, prev_sp_calls) for cat in CATEGORIES}
        sp_sum   = sum(sp_cats.values())
        if sp_sum != sp_calls:
            sp_cats["oth"] = max(0, sp_cats["oth"] + (sp_calls - sp_sum))
    else:
        sp_calls = 0
        sp_cats  = {cat: 0 for cat in CATEGORIES}

    sp_gross = max(sp_calls, round(scale(prev_sp.get("gross", 0), sp_calls, prev_sp_calls) if prev_sp_calls > 0 else 0))
    all_clinic_entries[special_key] = {
        **sp_cats,
        "total":       sp_calls,
        "slot_booked": sp_gross,
        "gross":       sp_gross,
        "calls_done":  sp_calls,
        "no_show":     max(0, sp_gross - sp_calls),
        "rescheduled": 0,
        "b2d_pct":     round(sp_calls / sp_gross * 100, 1) if sp_gross else 0.0,
        "ns_pct":      round(max(0, sp_gross - sp_calls) / sp_gross * 100, 1) if sp_gross else 0.0,
    }

d["all"]["weekly_clinic"][NEW_WK] = all_clinic_entries

# ── Write data.json ────────────────────────────────────────────────────────────
with open(DATA_JSON, "w") as f:
    json.dump(d, f, separators=(",", ":"))

# ── Sanity output ──────────────────────────────────────────────────────────────
print(f"✓ Wrote {DATA_JSON}  ({len(clinic_entries)} offline clinics)")
print()
print(f"{'Clinic key':<35} {'Sheet Bk':>8}  {'calls':>6}  {'gross':>6}  {'b2d%':>6}")
print("-" * 68)
for ck in sorted(clinic_entries.keys()):
    v  = clinic_entries[ck]
    bk = CLINIC_BK.get(ck, 0)
    print(f"  {ck:<33} {bk:>8}  {v['calls_done']:>6}  {v['gross']:>6}  {v['b2d_pct']:>6}%")

# Verify city sums
print()
print("City sum check:")
city_sums = defaultdict(int)
for ck, v in clinic_entries.items():
    city = ck.split("_", 1)[0]
    city_sums[city] += v["calls_done"]
for city, total in sorted(city_sums.items()):
    expected = city_calls_target.get(city, 0)
    ok = "✓" if total == expected else "✗"
    print(f"  {ok} {city:<15}: clinic sum={total:>4}  city target={expected:>4}")
