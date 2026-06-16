#!/usr/bin/env python3
"""Attach per-campaign weekly LEADS + BOOKED (UTM/gclid-attributed) to data_ga_campaigns.json.

Source: /tmp/ga_leads.tsv (wk · utm_campaign · leads · booked) — the same gclid→lead→booking
pull that feeds build_ga_funnel (fetch_ga_leads.sql). UTM/web leads ARE per-campaign attributable
(the phone pool is shared, but utm_campaign is on the web lead), so this is meaningful per campaign.
Matched to data_ga_campaigns by exact campaign name (≈60/70 match; non-matches get 0s).
Adds c['leads'] and c['booked'] (newest-first, aligned to each campaign's weeks_iso).
Run after pull_ga_campaigns.py + the ga_leads TSV step.
"""
import os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TSV = "/tmp/ga_leads.tsv"
CAMP_JSON = os.path.join(ROOT, "data_ga_campaigns.json")

def main():
    if not os.path.exists(TSV):
        print("no /tmp/ga_leads.tsv — run the GA gclid step first; skipping"); return
    # {campaign: {monday: [leads, booked]}}
    by = {}
    for line in open(TSV):
        p = line.rstrip("\n").split("\t")
        if len(p) < 4: continue
        wk, camp, leads, booked = p[0], p[1], p[2], p[3]
        done = p[4] if len(p) > 4 else 0
        try: leads, booked, done = int(float(leads)), int(float(booked)), int(float(done))
        except ValueError: continue
        by.setdefault(camp, {})[wk] = [leads, booked, done]
    d = json.load(open(CAMP_JSON)); n_match = 0
    for c in d["campaigns"]:
        wk_iso = c.get("weeks_iso") or []
        m = by.get(c["n"])
        if m: n_match += 1
        c["leads"]  = [ (m.get(w, [0, 0, 0])[0] if m else None) for w in wk_iso ]
        c["booked"] = [ (m.get(w, [0, 0, 0])[1] if m else None) for w in wk_iso ]
        c["done"]   = [ (m.get(w, [0, 0, 0])[2] if m else None) for w in wk_iso ]
    json.dump(d, open(CAMP_JSON, "w"), separators=(",", ":"))
    print(f"enriched {n_match}/{len(d['campaigns'])} campaigns with per-campaign leads/booked")

if __name__ == "__main__":
    main()
