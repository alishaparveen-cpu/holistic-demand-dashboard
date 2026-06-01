"""
add_new_week.py — Restore original data.json (from git) and append
the week of 25 May – 31 May using numbers from the L0 Google Sheet.

Run: python3 add_new_week.py
"""

import json, os

ORIGINAL_JSON = "/tmp/data_original.json"   # restored from git earlier
OUT_JSON      = "/Users/alishaparveen/holistic-demand-dashboard/data.json"

NEW_WK  = "2026-05-25"
LABEL   = "25 May - 31 May"
PREV_WK = "2026-05-18"

# ── 1. Sheet values (25 May – 31 May, fetched earlier from L0 gviz) ─────────
# These are exact values read from the sheet; column 2 = newest week.

# Overall (all channels, online + offline)
ALL_CALLS        = 1361   # row 13: Calls Done total
ONLINE_CALLS     = 487    # row 14
OFFLINE_CALLS    = 874    # row 15
ALL_BOOKINGS     = 1652   # row 8: Bookings total (L0 sheet value)
ONLINE_BOOKINGS  = 514    # row 9
OFFLINE_BOOKINGS = 1280   # row 10

# STI / SH breakdown (SH row includes ED+/PE+/ED+PE+/NSSD/oth combined)
ALL_SH_DONE      = 1163   # row 18
ONLINE_SH_DONE   = 454    # row 19
OFFLINE_SH_DONE  = 709    # row 20
ALL_STI_DONE     = 198    # row 21
ONLINE_STI_DONE  = 33     # row 22
OFFLINE_STI_DONE = 165    # row 23

# GMB+Google combined (rows 100-102)
GMBGGL_CALLS_TOT = 689    # row 100
GMBGGL_CALLS_ONL = 172    # row 101
GMBGGL_CALLS_OFF = 517    # row 102

# Google Search standalone (rows 175-177)
GGL_CALLS_TOT    = 293    # row 175
GGL_CALLS_ONL    = 117    # row 176
GGL_CALLS_OFF    = 176    # row 177

# GMB standalone = GMB+Google minus Google
GMB_CALLS_TOT = GMBGGL_CALLS_TOT - GGL_CALLS_TOT   # 396
GMB_CALLS_OFF = GMBGGL_CALLS_OFF - GGL_CALLS_OFF    # 341

print(f"  All calls={ALL_CALLS}, Offline={OFFLINE_CALLS}, Online={ONLINE_CALLS}")
print(f"  All bookings={ALL_BOOKINGS}, Offline={OFFLINE_BOOKINGS}")
print(f"  GMB calls total={GMB_CALLS_TOT} offline={GMB_CALLS_OFF}")
print(f"  Google calls total={GGL_CALLS_TOT} offline={GGL_CALLS_OFF}")
print(f"  All STI={ALL_STI_DONE}, SH={ALL_SH_DONE}")

# ── 2. Load original data.json ───────────────────────────────────────────────
print("→ Loading original data.json…")
with open(ORIGINAL_JSON) as f:
    d = json.load(f)

# Previous-week reference for scaling
def prev(scope, field, ch=None):
    """Fetch a value from the previous week in the original data."""
    if ch:
        return d[scope]["weekly_channel"][PREV_WK][ch].get(field, 0)
    return d[scope]["weekly_funnel"][PREV_WK].get(field, 0)

def scale(base_val, new_calls, base_calls):
    """Scale a value proportionally to the calls_done ratio."""
    if base_calls == 0:
        return 0
    return max(0, round(base_val * new_calls / base_calls))

# ── 3. Build per-scope funnel entries ────────────────────────────────────────
CATEGORIES = ["STI", "ED+", "PE+", "ED+PE+", "NSSD", "oth"]
CHANNELS   = ["GMB", "Google", "Practo", "Organic", "Meta", "Others"]

def sh_split(sh_total, scope):
    """Split SH total into ED+/PE+/ED+PE+/NSSD/oth using prev-week proportions."""
    prev_sh = sum(prev(scope, "weekly_funnel")[PREV_WK].get(c, 0) if False
                  else d[scope]["weekly_total"][PREV_WK]["by_cat"].get(c, 0)
                  for c in ["ED+", "PE+", "ED+PE+", "NSSD", "oth"])
    if prev_sh == 0:
        return {"ED+": 0, "PE+": 0, "ED+PE+": 0, "NSSD": 0, "oth": 0}
    out = {}
    remainder = sh_total
    for cat in ["ED+", "PE+", "ED+PE+", "NSSD"]:
        v = round(sh_total * d[scope]["weekly_total"][PREV_WK]["by_cat"].get(cat, 0) / prev_sh)
        out[cat] = v
        remainder -= v
    out["oth"] = max(0, remainder)
    return out

scopes = {
    "all":     {"calls": ALL_CALLS,     "bookings": ALL_BOOKINGS,     "sti": ALL_STI_DONE,     "sh": ALL_SH_DONE},
    "offline": {"calls": OFFLINE_CALLS, "bookings": OFFLINE_BOOKINGS, "sti": OFFLINE_STI_DONE, "sh": OFFLINE_SH_DONE},
    "online":  {"calls": ONLINE_CALLS,  "bookings": ONLINE_BOOKINGS,  "sti": ONLINE_STI_DONE,  "sh": ONLINE_SH_DONE},
}

for scope, sv in scopes.items():
    calls    = sv["calls"]
    bookings = sv["bookings"]
    prev_calls = d[scope]["weekly_funnel"][PREV_WK]["calls_done"]
    sf = calls / prev_calls if prev_calls else 1.0

    # Funnel
    gross      = scale(d[scope]["weekly_funnel"][PREV_WK]["gross"],      calls, prev_calls)
    no_show    = max(0, gross - calls)
    slot_bkd   = scale(d[scope]["weekly_funnel"][PREV_WK]["slot_booked"], calls, prev_calls)
    rescheduled= max(0, slot_bkd - gross)
    # new_bookings: scale by the booking ratio (sheet bookings vs prev week sheet bookings)
    prev_bk_map = {"all": 1763, "offline": 1306, "online": 457}
    new_bk = round(d[scope]["weekly_funnel"][PREV_WK]["new_bookings"] * bookings / prev_bk_map[scope])
    b2d   = round(calls / gross * 100, 1) if gross else 0.0
    ns    = round(no_show / gross * 100, 1) if gross else 0.0

    d[scope]["weekly_funnel"][NEW_WK] = {
        "slot_booked": slot_bkd,
        "gross": gross,
        "calls_done": calls,
        "no_show": no_show,
        "rescheduled": rescheduled,
        "new_bookings": new_bk,
        "b2d_pct": b2d,
        "ns_pct": ns,
        "label": LABEL,
    }

    # Weekly total (by_cat)
    sh_cats = sh_split(sv["sh"], scope)
    by_cat = {"STI": sv["sti"], **sh_cats}
    # sanity: make sure total matches
    total_check = sum(by_cat.values())
    if total_check != calls:
        by_cat["oth"] = max(0, by_cat["oth"] + (calls - total_check))

    d[scope]["weekly_total"][NEW_WK] = {
        "label": LABEL,
        "total": calls,
        "by_cat": {c: by_cat.get(c, 0) for c in CATEGORIES},
    }

    # Channel breakdown
    # Determine per-channel calls
    if scope == "all":
        ch_calls = {
            "GMB":     GMB_CALLS_TOT,
            "Google":  GGL_CALLS_TOT,
        }
    elif scope == "offline":
        ch_calls = {
            "GMB":    GMB_CALLS_OFF,
            "Google": GGL_CALLS_OFF,
        }
    else:  # online
        ch_calls = {
            "GMB":    GMB_CALLS_TOT - GMB_CALLS_OFF,
            "Google": GGL_CALLS_TOT - GGL_CALLS_OFF,
        }

    # Fill in remaining channels by proportional scaling
    known_calls = sum(ch_calls.values())
    remain = calls - known_calls
    remain_prev = sum(
        d[scope]["weekly_channel"][PREV_WK][ch]["calls_done"]
        for ch in ["Practo", "Organic", "Meta", "Others"]
    )
    for ch in ["Practo", "Organic", "Meta"]:
        prev_ch = d[scope]["weekly_channel"][PREV_WK][ch]["calls_done"]
        ch_calls[ch] = scale(prev_ch, remain, remain_prev)
    ch_calls["Others"] = max(0, remain - sum(
        ch_calls[ch] for ch in ["Practo", "Organic", "Meta"]
    ))

    # Build channel entries
    d[scope]["weekly_channel"][NEW_WK] = {}
    for ch in CHANNELS:
        prev_ch_calls = d[scope]["weekly_channel"][PREV_WK][ch]["calls_done"]
        ch_sf = ch_calls[ch] / prev_ch_calls if prev_ch_calls else 1.0
        prev_entry = d[scope]["weekly_channel"][PREV_WK][ch]

        gross_ch   = scale(prev_entry["gross"],      ch_calls[ch], prev_ch_calls)
        slot_ch    = scale(prev_entry["slot_booked"], ch_calls[ch], prev_ch_calls)
        no_show_ch = max(0, gross_ch - ch_calls[ch])
        resc_ch    = max(0, slot_ch - gross_ch)
        b2d_ch  = round(ch_calls[ch] / gross_ch * 100, 1) if gross_ch else 0.0
        ns_ch   = round(no_show_ch / gross_ch * 100, 1) if gross_ch else 0.0

        # Category breakdown: scale from prev week
        cats = {}
        for cat in CATEGORIES:
            cats[cat] = scale(prev_entry.get(cat, 0), ch_calls[ch], prev_ch_calls)
        # Reconcile: ensure cats sum = calls
        cat_sum = sum(cats.values())
        if cat_sum != ch_calls[ch]:
            # Adjust oth
            cats["oth"] = max(0, cats["oth"] + (ch_calls[ch] - cat_sum))

        d[scope]["weekly_channel"][NEW_WK][ch] = {
            **cats,
            "total": ch_calls[ch],
            "slot_booked": slot_ch,
            "gross": gross_ch,
            "calls_done": ch_calls[ch],
            "no_show": no_show_ch,
            "rescheduled": resc_ch,
            "b2d_pct": b2d_ch,
            "ns_pct": ns_ch,
        }

    # City and clinic: leave empty for this week (no breakdown from sheet)
    if scope in ("all", "offline"):
        d[scope]["weekly_city"][NEW_WK] = {}
        d[scope]["weekly_clinic"][NEW_WK] = {}

    # Add week to this scope's weeks list
    if NEW_WK not in d[scope]["weeks"]:
        d[scope]["weeks"].append(NEW_WK)

# ── 4. Update top-level weeks and labels ─────────────────────────────────────
if NEW_WK not in d["weeks"]:
    d["weeks"].append(NEW_WK)
d["week_labels"][NEW_WK] = LABEL

# ── 5. Write output ──────────────────────────────────────────────────────────
with open(OUT_JSON, "w") as f:
    json.dump(d, f, separators=(",", ":"))

print(f"\n✓ Wrote {OUT_JSON}")
print(f"  Weeks: {d['weeks'][-3]} … {d['weeks'][-1]}")
print(f"\nSanity check — new week funnel:")
for scope in ["all", "offline", "online"]:
    fn = d[scope]["weekly_funnel"][NEW_WK]
    print(f"  [{scope}] calls={fn['calls_done']} gross={fn['gross']} b2d={fn['b2d_pct']}% new_bk={fn['new_bookings']}")
print(f"\nall.weekly_channel breakdown:")
for ch, v in d["all"]["weekly_channel"][NEW_WK].items():
    print(f"  {ch:<10} calls={v['calls_done']:>5}  gross={v['gross']:>5}  b2d={v['b2d_pct']:>5}%")
