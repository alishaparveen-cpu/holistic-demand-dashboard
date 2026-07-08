#!/usr/bin/env python3
"""Build data_practo_flow_booked.json — Practo DIRECT bookings from the Flow-Dashboard export
(data_practo_flow.csv). A direct booking = a row with type='Book' and net_amount > 0 (a paid
appointment booked directly on Practo, distinct from enquiry/'Call' leads).

Keyed by clinic locality (the CSV's `location` column), weekly arrays newest-first. The channel
view sums these nationally (prAlign). Purely local — reads the CSV, no Redshift/Sheets.
This is SEPARATE from data_practo_booked.json (phone-match attribution, used by diagnostic/marketing)
so those views are unaffected.
Run: python3 scripts/build_practo_flow_booked.py
"""
import csv, os, json, datetime
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(ROOT, "data_practo_flow.csv")
OUT = os.path.join(ROOT, "data_practo_flow_booked.json")

def monday(d):
    return (d - datetime.timedelta(days=d.weekday())).isoformat()

def main():
    perloc = defaultdict(lambda: defaultdict(int))   # locality -> monday -> count
    weeks = set()
    with open(CSV_PATH) as f:
        for r in csv.DictReader(f):
            if (r.get("type") or "").strip() != "Book":
                continue
            try:
                net = float(r.get("net_amount") or 0)
            except ValueError:
                net = 0
            if net <= 0:
                continue
            try:
                d = datetime.datetime.strptime(r["dt"], "%d-%m-%Y").date()
            except (ValueError, KeyError):
                continue
            if d.year < 2025:   # drop the 1899 junk + ancient rows
                continue
            loc = (r.get("location") or "").strip() or "(unknown)"
            wk = monday(d)
            perloc[loc][wk] += 1
            weeks.add(wk)
    WEEKS = sorted(weeks, reverse=True)   # newest-first
    out = {"_meta": {"source": "Practo Flow-Dashboard export · direct bookings (type=Book, net_amount>0)",
                     "weeks": WEEKS, "pulled": WEEKS[0] if WEEKS else None,
                     "note": "per clinic locality, weekly Book-with-net>0 counts. Distinct from data_practo_booked.json (phone-match)."}}
    for loc, wkmap in perloc.items():
        out[loc] = [wkmap.get(w, 0) for w in WEEKS]
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    natl = [sum(out[loc][i] for loc in out if loc != "_meta") for i in range(len(WEEKS))]
    print(f"wrote {OUT} · {len(perloc)} localities · weeks {WEEKS[0]}..{WEEKS[-1]}")
    print(f"  national direct-bookings (recent 6 wks): {natl[:6]}")


if __name__ == "__main__":
    main()
