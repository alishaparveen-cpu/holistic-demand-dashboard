#!/usr/bin/env python3
"""Merge data_ga_city_paid.json (Google Ads city layer) into data_source_recon.json's
_meta.city_google_reach — impressions/clicks/loc_clicks + by_cat (impr/clicks/loc_clicks/conv),
grid-aligned. Run after pull_ga_city_paid.py + build_clinic_wow.py.
"""
import os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.join(ROOT, "data_source_recon.json")))
ga = json.load(open(os.path.join(ROOT, "data_ga_city_paid.json")))
W = d["_meta"]["weeks"]; NW = len(W); pos = {w: i for i, w in enumerate(W)}
gw = ga["_meta"]["weeks"]; CATS = ["STI", "SH", "MH", "Other"]

def align(arr):
    o = [None] * NW
    for j, wk in enumerate(gw):
        if wk in pos and j < len(arr):
            try: o[pos[wk]] = arr[j]
            except Exception: pass
    return o

reach = {}
for city, c in ga.items():
    if city.startswith("_"): continue
    impr = align(c.get("impr", []))
    if not any(v for v in impr): continue
    by_cat = {}
    for ct in CATS:
        bc = c.get("by_cat", {}).get(ct, {})
        ci = align(bc.get("impr", []))
        if not any(v for v in ci): continue
        by_cat[ct] = {"impr": ci, "clicks": align(bc.get("clicks", [])),
                      "loc_clicks": align(bc.get("loc_clicks", [])), "conv": align(bc.get("conv", []))}
    reach[city] = {"impr": impr, "clicks": align(c.get("clicks", [])),
                   "loc_clicks": align(c.get("loc_clicks", [])), "by_cat": by_cat}
d["_meta"]["city_google_reach"] = reach
json.dump(d, open(os.path.join(ROOT, "data_source_recon.json"), "w"), separators=(",", ":"))
print("merged GA reach for %d cities" % len(reach))
