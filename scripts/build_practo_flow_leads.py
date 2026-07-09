#!/usr/bin/env python3
"""Build data_practo_flow_leads.json — Practo LEADS from the Flow-Dashboard export
(data_practo_flow.csv). Per Alisha: BOTH row types (Book + Call) are leads, and we keep only
rows where the Platform Development Fee was actually collected → net_amount > 0.

  net_amount = amount - amount_refunded  (fee net of refunds)
  filter:      net_amount > 0            (any type — Book OR Call)

Keyed by clinic locality (the CSV's `location` column), weekly arrays newest-first. The channel
view sums these nationally (prAlign). Purely local — reads the CSV, no Redshift/Sheets.
Run: python3 scripts/build_practo_flow_leads.py
"""
import csv, os, json, datetime
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(ROOT, "data_practo_flow.csv")
OUT = os.path.join(ROOT, "data_practo_flow_leads.json")

def monday(d):
    return (d - datetime.timedelta(days=d.weekday())).isoformat()

def main():
    perloc = defaultdict(lambda: defaultdict(int))   # locality -> monday -> count
    weeks = set()
    kept = by_type = {"Book": 0, "Call": 0}
    tally = {"Book": 0, "Call": 0, "other": 0}
    with open(CSV_PATH) as f:
        for r in csv.DictReader(f):
            try:
                net = float(r.get("net_amount") or 0)
            except ValueError:
                net = 0
            if net <= 0:                      # only where the Platform Development Fee was collected
                continue
            try:
                d = datetime.datetime.strptime(r["dt"], "%d-%m-%Y").date()
            except (ValueError, KeyError):
                continue
            if d.year < 2024:                 # drop ancient rows; channel grid only aligns recent weeks
                continue
            loc = (r.get("location") or "").strip() or "(unknown)"
            perloc[loc][monday(d)] += 1
            weeks.add(monday(d))
            t = (r.get("type") or "").strip()
            tally[t if t in tally else "other"] += 1
    WEEKS = sorted(weeks, reverse=True)   # newest-first
    out = {"_meta": {"source": "Practo Flow-Dashboard export · LEADS (Book + Call, net_amount>0 = fee collected)",
                     "weeks": WEEKS, "pulled": WEEKS[0] if WEEKS else None,
                     "note": "per clinic locality, weekly count of Practo rows with net_amount>0 (both Book & Call = leads). Distinct from data_practo_flow_booked.json (type=Book only) and data_practo_booked.json (phone-match)."}}
    for loc, wkmap in perloc.items():
        out[loc] = [wkmap.get(w, 0) for w in WEEKS]
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    natl = [sum(out[loc][i] for loc in out if loc != "_meta") for i in range(len(WEEKS))]
    print(f"wrote {OUT} · {len(perloc)} localities · weeks {WEEKS[-1]}..{WEEKS[0]}")
    print(f"  kept rows by type: {tally}")
    print(f"  national Practo leads (recent 6 wks, newest-first): {natl[:6]}")


if __name__ == "__main__":
    main()
