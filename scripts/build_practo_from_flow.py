#!/usr/bin/env python3
"""Build data_practo_flow_leads.json — per-clinic weekly Practo counts from the Practo
"Flow Dashboard" export (data_practo_flow.csv).

Definition (per user, 2026-07-07): a Practo lead = a flow row with amount (col C) > 0.
Counts Book + Call rows alike (matches the old RD_Practo_Leads sheet's ~300/wk magnitude),
grouped by clinic × ISO-week (Monday), aligned to data_weekly_diag.json's week grid.

Location reconciliation uses PRACTO_ALIAS (Practo Practice-Locality → clinic locality),
audited in reference_practo_clinic_reconciliation. 5 orphan localities with no active
clinic are dropped (logged): Attapur, Borabanda, Greater Kailash, Mahalakshmi Layout,
Sushant Lok I.

Output is keyed by clinic SLUG so patch_practo_into_demand.py can inject directly.
Purely local (reads the CSV); no Redshift / Sheets fetch.

Run:  python3 scripts/build_practo_from_flow.py    (from hdd-live)
"""
import csv, os, json, datetime
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(ROOT, "data_practo_flow.csv")
WD_PATH = os.path.join(ROOT, "data_weekly_diag.json")
OUT_PATH = os.path.join(ROOT, "data_practo_flow_leads.json")

# Practo Practice-Locality string  ->  clinic locality in weekly_diag (loc-only; all locs unique)
PRACTO_ALIAS = {
    "electronics city": "electronic city",
    "sahakaranagar": "sahakara nagar",
    "borivali east": "borivali",
    "dadar west": "dadar",
    "pimpri-chinchwad": "chinchwad",
    "okkiyam thuraipakkam": "thoraipakkam",
    "gulmohar colony": "gulmohar",
    "suryaraopet": "suryaraopeta",
    "hubli vidyanagar": "vidya nagar",
    "khatipura": "vaishali nagar",
    "bariatu": "ashok nagar",
    "mankapur ring road": "tatya tope nagar",
    "falnir": "falnir rd",
    "thane west": "thane",
}
# Practo localities with no active clinic in our network → drop
ORPHANS = {"attapur", "borabanda", "greater kailash", "mahalakshmi layout", "sushant lok i", "#n/a", ""}

def monday(dstr):
    try:
        dd = datetime.datetime.strptime(dstr, "%d-%m-%Y").date()
    except ValueError:
        return None
    return (dd - datetime.timedelta(days=dd.weekday())).isoformat()

def main():
    with open(WD_PATH) as f:
        wd = json.load(f)
    weeks = wd["weeks"]                      # 26 Monday dates, ascending
    N = len(weeks)
    widx = {w: i for i, w in enumerate(weeks)}
    # loc(lower) -> slug
    loc2slug = {(c.get("loc") or "").strip().lower(): slug for slug, c in wd["clinics"].items()}

    counts = defaultdict(lambda: [0] * N)   # slug -> weekly array
    dropped = defaultdict(int)              # orphan loc -> rows dropped
    off_grid = 0                            # amount>0 rows whose week is outside the 26-wk grid
    total = 0
    with open(CSV_PATH) as f:
        for r in csv.DictReader(f):
            try:
                amt = float(r.get("amount") or 0)
            except ValueError:
                amt = 0
            if amt <= 0:
                continue
            loc = (r.get("location") or "").strip()
            key = PRACTO_ALIAS.get(loc.lower(), loc.lower())
            slug = loc2slug.get(key)
            if not slug:
                dropped[loc.lower()] += 1
                continue
            m = monday(r.get("dt", ""))
            i = widx.get(m)
            if i is None:
                off_grid += 1
                continue
            counts[slug][i] += 1
            total += 1

    out = {"_meta": {"source": "data_practo_flow.csv (Practo Flow Dashboard) · lead = row with amount>0 (Book+Call)",
                     "weeks": weeks, "built_for_grid": "data_weekly_diag.json"},
           "clinics": {s: counts[s] for s in counts}}
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, separators=(",", ":"))

    print(f"[practo-flow] {total} amount>0 rows → {len(counts)} clinics on the {N}-wk grid")
    print(f"[practo-flow] {off_grid} amount>0 rows outside the grid (older/newer than the 26 wks) — expected")
    if dropped:
        drp = sorted(((v, k) for k, v in dropped.items() if k not in ("#n/a", "")), reverse=True)
        print(f"[practo-flow] dropped {sum(v for v, _ in drp)} rows at {len(drp)} orphan localities (no active clinic): "
              + ", ".join(f"{k}({v})" for v, k in drp))

if __name__ == "__main__":
    main()
