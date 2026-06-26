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
                      "loc_clicks": align(bc.get("loc_clicks", [])), "conv": align(bc.get("conv", [])),
                      "spend": align(bc.get("spend", []))}
    by_seg = {}
    for sg in ("offline", "online"):
        sd = c.get("by_seg", {}).get(sg, {})
        if not sd: continue
        by_seg[sg] = {"impr": align(sd.get("impr", [])), "clicks": align(sd.get("clicks", [])),
                      "loc_clicks": align(sd.get("loc_clicks", [])), "spend": align(sd.get("spend", [])),
                      "by_cat": {ct: {"impr": align(sd.get("by_cat", {}).get(ct, {}).get("impr", [])),
                                      "clicks": align(sd.get("by_cat", {}).get(ct, {}).get("clicks", [])),
                                      "loc_clicks": align(sd.get("by_cat", {}).get(ct, {}).get("loc_clicks", [])),
                                      "spend": align(sd.get("by_cat", {}).get(ct, {}).get("spend", []))} for ct in CATS}}
    reach[city] = {"impr": impr, "clicks": align(c.get("clicks", [])),
                   "loc_clicks": align(c.get("loc_clicks", [])), "spend": align(c.get("spend", [])),
                   "by_cat": by_cat, "by_seg": by_seg}
d["_meta"]["city_google_reach"] = reach
no = ga.get("_national_online", {})
if no:
    d["_meta"]["google_online_national"] = {"impr": align(no.get("impr", [])), "clicks": align(no.get("clicks", [])),
        "spend": align(no.get("spend", [])), "conv": align(no.get("conv", [])),
        "by_cat": {ct: {"impr": align(no.get("by_cat", {}).get(ct, {}).get("impr", [])),
                        "clicks": align(no.get("by_cat", {}).get(ct, {}).get("clicks", [])),
                        "spend": align(no.get("by_cat", {}).get(ct, {}).get("spend", []))} for ct in CATS}}
json.dump(d, open(os.path.join(ROOT, "data_source_recon.json"), "w"), separators=(",", ":"))
print("merged GA reach for %d cities" % len(reach))
