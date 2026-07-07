#!/usr/bin/env python3
"""Merge Practo leads into data_weekly_diag.json's per-clinic demand.by_channel
so the marketing view's "Practo" source filter populates.

Source: data_practo_flow_leads.json (built by build_practo_from_flow.py from the Practo
Flow Dashboard CSV — lead = flow row with amount>0). Keyed by clinic slug, already aligned
to weekly_diag's 26-week grid.

- Idempotent: re-running overwrites the Practo channel (safe after a weekly_diag rebuild).
- NB: Practo is additive — it is NOT part of demand.leads (the tagged-lead total). It shows as
  its own channel row / source scope only. This matches how the source view reads by_channel.
- Purely local: no Redshift needed.

Run:  python3 scripts/build_practo_from_flow.py && python3 scripts/patch_practo_into_demand.py
"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WD_PATH = os.path.join(ROOT, "data_weekly_diag.json")
PR_PATH = os.path.join(ROOT, "data_practo_flow_leads.json")

def main():
    with open(WD_PATH) as f: d = json.load(f)
    with open(PR_PATH) as f: pr = json.load(f)

    N = len(d["weeks"])
    cube = pr.get("clinics", {})
    matched, total_leads = 0, 0
    for slug, arr in cube.items():
        c = d["clinics"].get(slug)
        if not c:
            continue
        arr = (arr + [0] * N)[:N]
        c.setdefault("demand", {}).setdefault("by_channel", {})["Practo"] = arr
        matched += 1
        total_leads += sum(arr)

    with open(WD_PATH, "w") as f:
        json.dump(d, f, separators=(",", ":"))
    print(f"[practo-merge] injected Practo into {matched} clinics · {total_leads} total leads (from {os.path.basename(PR_PATH)})")

if __name__ == "__main__":
    main()
