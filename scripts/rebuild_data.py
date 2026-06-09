"""
Rebuild data.json from /tmp/bookings_full.csv using MONDAY-starting weeks
(Mon–Sun) to match the Google Sheet's week definition.

Run: python3 rebuild_data.py
"""

import csv
import json
import os
from collections import defaultdict
from datetime import datetime, date, timedelta

import os as _os
CSV_PATH = "/tmp/bookings_full.csv"
OUT_PATH = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "data.json")  # repo root

# Number of complete Mon–Sun weeks to include (most recent first)
NUM_WEEKS = 12

CATEGORIES = ["STI", "ED+", "PE+", "ED+PE+", "NSSD", "oth"]
CHANNELS   = ["GMB", "Google", "Practo", "Organic", "Meta", "Others"]


def week_start_monday(d: date) -> date:
    """Return the Monday that starts the week containing date d."""
    return d - timedelta(days=d.weekday())  # weekday() 0=Mon … 6=Sun


def map_channel(src: str) -> str:
    s = src.strip().lower()
    if s.startswith("gmb"):
        return "GMB"
    if s.startswith("google"):
        return "Google"
    if s == "practo":
        return "Practo"
    if s.startswith("organic"):
        return "Organic"
    if s in ("fb", "ig", "instagram", "meta") or s.startswith("fb "):
        return "Meta"
    return "Others"


def map_cat(raw: str) -> str:
    c = raw.strip()
    return c if c in ("STI", "ED+", "PE+", "ED+PE+", "NSSD", "oth") else "oth"


def empty_funnel():
    return dict(
        slot_booked=0, gross=0, calls_done=0,
        no_show=0, rescheduled=0,
        new_bookings=0,
        b2d_pct=0.0, ns_pct=0.0,
    )


def empty_detail():
    d = {c: 0 for c in CATEGORIES}
    d.update(
        total=0,
        slot_booked=0, gross=0, calls_done=0,
        no_show=0, rescheduled=0,
        b2d_pct=0.0, ns_pct=0.0,
    )
    return d


def finalise_funnel(f: dict) -> dict:
    g = f["gross"]
    f["b2d_pct"] = round(f["calls_done"] / g * 100, 1) if g else 0.0
    f["ns_pct"]  = round(f["no_show"]    / g * 100, 1) if g else 0.0
    return f


def finalise_detail(d: dict) -> dict:
    g = d["gross"]
    d["b2d_pct"] = round(d["calls_done"] / g * 100, 1) if g else 0.0
    d["ns_pct"]  = round(d["no_show"]    / g * 100, 1) if g else 0.0
    return d


def build_section():
    """Returns empty accumulator dicts for one section (all/offline/online)."""
    return dict(
        funnel=defaultdict(empty_funnel),            # week → funnel
        total=defaultdict(lambda: {"total": 0, "by_cat": {c: 0 for c in CATEGORIES}}),
        channel=defaultdict(lambda: defaultdict(empty_detail)),   # week → ch → detail
        city=defaultdict(lambda: defaultdict(empty_detail)),      # week → city → detail
        clinic=defaultdict(lambda: defaultdict(empty_detail)),    # week → clinic_key → detail
        doctor=defaultdict(lambda: defaultdict(empty_detail)),    # week → "clinic_key|doctor" → detail
    )


def main():
    today = date.today()  # 2026-05-27

    # Build list of the last NUM_WEEKS complete Mon–Sun weeks
    # Most recent complete week ends on the last Sunday before today
    last_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    # If today is Monday, last_sunday = yesterday (Sunday) — that's correct
    # last_sunday is always a Sunday
    week_ends   = [last_sunday - timedelta(weeks=i) for i in range(NUM_WEEKS)]
    week_starts = [we - timedelta(days=6) for we in week_ends]  # Monday
    valid_weeks = set(ws.isoformat() for ws in week_starts)

    print(f"Weeks (Mon start → Sun end):")
    for ws, we in zip(week_starts, week_ends):
        print(f"  {ws} → {we}")

    # Accumulators: all / offline / online
    acc = {k: build_section() for k in ("all", "offline", "online")}

    rows_read = 0
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows_read += 1
            sched_raw  = row["apt_schedule_dt"].strip()
            create_raw = row["apt_create_dt"].strip()
            status     = row["apt_status_final"].strip()
            channel    = map_channel(row["Source final"])
            cat        = map_cat(row["diag_cat"])
            city       = row["city"].strip()
            locality   = row["locality"].strip()
            is_offline = row["offline_location_flag"].strip() == "1"
            scope_keys = ["all", "offline" if is_offline else "online"]
            clinic_key = f"{city}_{locality}" if city else f"_{locality}"
            doctor     = (row.get("doctor") or "").strip() or "(unassigned)"
            doctor_key = f"{clinic_key}|{doctor}"

            # --- schedule_dt slice ---
            if sched_raw:
                try:
                    sched_d = datetime.strptime(sched_raw, "%Y-%m-%d").date()
                except ValueError:
                    sched_d = None

                if sched_d:
                    wk = week_start_monday(sched_d).isoformat()
                    if wk in valid_weeks:
                        for sk in scope_keys:
                            a = acc[sk]

                            # aggregate-level funnel
                            fn = a["funnel"][wk]
                            fn["slot_booked"] += 1
                            if status == "COMPLETED":
                                fn["calls_done"] += 1; fn["gross"] += 1
                            elif status == "NO_SHOW":
                                fn["no_show"] += 1; fn["gross"] += 1
                            elif status == "RESCHEDULED":
                                fn["rescheduled"] += 1

                            # channel-level detail
                            ch_d = a["channel"][wk][channel]
                            ch_d["slot_booked"] += 1
                            if status == "COMPLETED":
                                ch_d["calls_done"] += 1; ch_d["gross"] += 1
                                ch_d["total"] += 1; ch_d[cat] += 1
                            elif status == "NO_SHOW":
                                ch_d["no_show"] += 1; ch_d["gross"] += 1
                            elif status == "RESCHEDULED":
                                ch_d["rescheduled"] += 1

                            # city-level detail (offline + all only)
                            if sk in ("all", "offline") and city:
                                ct_d = a["city"][wk][city]
                                ct_d["slot_booked"] += 1
                                if status == "COMPLETED":
                                    ct_d["calls_done"] += 1; ct_d["gross"] += 1
                                    ct_d["total"] += 1; ct_d[cat] += 1
                                elif status == "NO_SHOW":
                                    ct_d["no_show"] += 1; ct_d["gross"] += 1
                                elif status == "RESCHEDULED":
                                    ct_d["rescheduled"] += 1

                            # clinic-level detail (offline + all only)
                            if sk in ("all", "offline"):
                                cl_d = a["clinic"][wk][clinic_key]
                                cl_d["slot_booked"] += 1
                                if status == "COMPLETED":
                                    cl_d["calls_done"] += 1; cl_d["gross"] += 1
                                    cl_d["total"] += 1; cl_d[cat] += 1
                                elif status == "NO_SHOW":
                                    cl_d["no_show"] += 1; cl_d["gross"] += 1
                                elif status == "RESCHEDULED":
                                    cl_d["rescheduled"] += 1

                            # doctor-level detail (offline + all only) — one depth below clinic
                            if sk in ("all", "offline"):
                                dc_d = a["doctor"][wk][doctor_key]
                                dc_d["slot_booked"] += 1
                                if status == "COMPLETED":
                                    dc_d["calls_done"] += 1; dc_d["gross"] += 1
                                    dc_d["total"] += 1; dc_d[cat] += 1
                                elif status == "NO_SHOW":
                                    dc_d["no_show"] += 1; dc_d["gross"] += 1
                                elif status == "RESCHEDULED":
                                    dc_d["rescheduled"] += 1

                            # weekly_total (COMPLETED only, with by_cat)
                            if status == "COMPLETED":
                                t = a["total"][wk]
                                t["total"] += 1
                                t["by_cat"][cat] += 1

            # --- create_dt slice (new_bookings = COMPLETED + NO_SHOW by create_dt) ---
            if create_raw and status in ("COMPLETED", "NO_SHOW"):
                try:
                    create_d = datetime.strptime(create_raw, "%Y-%m-%d").date()
                except ValueError:
                    create_d = None

                if create_d:
                    wk = week_start_monday(create_d).isoformat()
                    if wk in valid_weeks:
                        for sk in scope_keys:
                            acc[sk]["funnel"][wk]["new_bookings"] += 1

    print(f"\nRead {rows_read} rows from CSV")

    # --- Build week labels ---
    weeks_sorted = sorted(valid_weeks)
    week_labels = {}
    for ws_str in weeks_sorted:
        ws = date.fromisoformat(ws_str)
        we = ws + timedelta(days=6)
        label = f"{ws.strftime('%d %b')} - {we.strftime('%d %b')}"
        week_labels[ws_str] = label

    # --- Serialise ---
    def serialise_section(sk: str) -> dict:
        a   = acc[sk]
        out = {"weeks": weeks_sorted}

        # weekly_total
        wt = {}
        for wk in weeks_sorted:
            t = a["total"][wk]
            wt[wk] = {"label": week_labels[wk], "total": t["total"],
                       "by_cat": {c: t["by_cat"][c] for c in CATEGORIES}}
        out["weekly_total"] = wt

        # weekly_funnel
        wf = {}
        for wk in weeks_sorted:
            fn = finalise_funnel(dict(a["funnel"][wk]))
            fn["label"] = week_labels[wk]
            wf[wk] = fn
        out["weekly_funnel"] = wf

        # weekly_channel
        wch = {}
        for wk in weeks_sorted:
            wch[wk] = {}
            for ch in CHANNELS:
                d = finalise_detail(dict(a["channel"][wk].get(ch, empty_detail())))
                wch[wk][ch] = d
        out["weekly_channel"] = wch

        # weekly_city + weekly_clinic (only for all/offline)
        if sk in ("all", "offline"):
            all_cities = sorted({city for wk in weeks_sorted
                                  for city in a["city"][wk].keys()})
            out["cities"] = all_cities

            wci = {}
            for wk in weeks_sorted:
                wci[wk] = {}
                for city in all_cities:
                    if city in a["city"][wk]:
                        wci[wk][city] = finalise_detail(dict(a["city"][wk][city]))
            out["weekly_city"] = wci

            all_clinics = sorted({ck for wk in weeks_sorted
                                   for ck in a["clinic"][wk].keys()})
            out["clinics"] = all_clinics

            wcl = {}
            for wk in weeks_sorted:
                wcl[wk] = {}
                for ck in all_clinics:
                    if ck in a["clinic"][wk]:
                        wcl[wk][ck] = finalise_detail(dict(a["clinic"][wk][ck]))
            out["weekly_clinic"] = wcl

            # doctor dimension — keyed "clinic_key|Doctor Name" (one depth below clinic)
            all_doctors = sorted({dk for wk in weeks_sorted for dk in a["doctor"][wk].keys()})
            out["doctors"] = all_doctors
            wdc = {}
            for wk in weeks_sorted:
                wdc[wk] = {}
                for dk in all_doctors:
                    if dk in a["doctor"][wk]:
                        wdc[wk][dk] = finalise_detail(dict(a["doctor"][wk][dk]))
            out["weekly_doctor"] = wdc

        return out

    result = {
        "weeks":       weeks_sorted,
        "week_labels": week_labels,
        "categories":  CATEGORIES,
        "channels":    CHANNELS,
        "all":         serialise_section("all"),
        "offline":     serialise_section("offline"),
        "online":      serialise_section("online"),
        "meta": {
            "note": ("Funnel: schedule_dt for completed/no-show/rescheduled; "
                     "create_dt for new_bookings (COMPLETED+NO_SHOW). "
                     "Weeks: Monday–Sunday."),
            "data_source": "bookings_full.csv",
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "week_definition": "Monday start, Sunday end",
        },
    }

    with open(OUT_PATH, "w") as f:
        json.dump(result, f, separators=(",", ":"))

    size = os.path.getsize(OUT_PATH)
    print(f"\n✓ Wrote {OUT_PATH} ({size:,} bytes)")
    print(f"  {NUM_WEEKS} weeks: {weeks_sorted[0]} → {weeks_sorted[-1]}")

    # Quick sanity check
    wk_check = weeks_sorted[-2] if len(weeks_sorted) >= 2 else weeks_sorted[-1]
    td = result["all"]["weekly_funnel"][wk_check]
    print(f"\nSanity — all.weekly_funnel[{wk_check}]:")
    print(f"  calls_done={td['calls_done']}  gross={td['gross']}  "
          f"b2d={td['b2d_pct']}%  new_bk={td['new_bookings']}")


if __name__ == "__main__":
    main()
