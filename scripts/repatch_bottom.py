#!/usr/bin/env python3
"""Recompute bottom (total + by_cat) for ALL clinics in data_source_recon.json after the
category-mapping fix ('others' diagnosis tag → SH, not Other). Resumable via _bottom_v2 flag.
Run: AWS_PROFILE=redshift-data python3 scripts/repatch_bottom.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import build_clinic_wow as W
import build_mh_funnels as B

ROOT = W.ROOT; OUT = os.path.join(ROOT, "data_source_recon.json")
d = json.load(open(OUT)); CFG = W.CFG
done = 0
items = list(d["clinics"].items())
for slug, c in items:
    if c.get("bottom", {}).get("_v2"):   # already repatched
        continue
    cfg = CFG.get(slug)
    if not cfg:
        continue
    try:
        bfull = B.get_bottom(cfg)
        c["bottom"]["total"] = bfull["total"]
        c["bottom"]["by_cat"] = bfull.get("by_cat", {})
        c["bottom"]["_v2"] = True
        done += 1
        bc = bfull["by_cat"]
        print("[ok %d/%d] %s  done SH %s STI %s MH %s Oth %s" % (
            done, len(items), cfg["disp"],
            bc["SH"]["done"][1], bc["STI"]["done"][1], bc["MH"]["done"][1], bc["Other"]["done"][1]), flush=True)
        if done % 5 == 0:
            json.dump(d, open(OUT, "w"), separators=(",", ":"))
    except BaseException as e:
        print("[FAIL] %s: %s" % (cfg.get("disp", slug), type(e).__name__), flush=True)
json.dump(d, open(OUT, "w"), separators=(",", ":"))
print("repatched %d clinics" % done)
