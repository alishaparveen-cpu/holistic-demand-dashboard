#!/usr/bin/env python3
"""Build data_leads_total.json — network-wide total inbound leads per week (the true top of the
category demand funnel). Keyed by Monday-week date. Run: python3 scripts/build_leads_total.py"""
import json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sql = open(os.path.join(ROOT, "scripts", "fetch_leads_total.sql")).read()
p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "redshift_query.py")],
                   input=sql, capture_output=True, text=True)
if p.returncode != 0 or "ERROR" in p.stderr:
    sys.stderr.write("fetch_leads_total.sql failed: " + (p.stderr or "")[:300] + "\n"); sys.exit(1)
totals = {}
for line in p.stdout.strip().splitlines():
    parts = line.split("\t")
    if len(parts) >= 2 and parts[0]:
        try: totals[parts[0]] = int(float(parts[1]))
        except ValueError: pass
out = {"_meta": {"source": "production.public.main_source_wise_leads (all sources, all call_locations)",
                 "note": "Network total inbound leads/week — true top-of-funnel. Excludes Practo (external feed). "
                         "Most leads have no call_location so this is NOT clinic-attributable.",
                 "keyed_by": "Monday-of-week (YYYY-MM-DD)"},
       "totals": totals}
json.dump(out, open(os.path.join(ROOT, "data_leads_total.json"), "w"), separators=(",", ":"))
print("data_leads_total.json ·", len(totals), "weeks · latest",
      max(totals) if totals else "-", "=", totals.get(max(totals)) if totals else "-")
