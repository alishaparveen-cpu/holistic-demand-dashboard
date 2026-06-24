#!/usr/bin/env python3
"""Patch category (STI/SH/MH/Other) into data_source_recon.json without a full rebuild:
  bottom.by_cat (done/purchased/rev by category) + gmb_call/gpaid_call .by_cat (answered calls by category).
Resumable: skips clinics already carrying bottom.by_cat. Saves every 5.
Run: AWS_PROFILE=redshift-data python3 scripts/patch_category.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import build_clinic_wow as W
import build_mh_funnels as B

ROOT = W.ROOT; OUT = os.path.join(ROOT, "data_source_recon.json")
d = json.load(open(OUT))
CFG = W.CFG
done = 0
items = list(d["clinics"].items())
for n, (slug, c) in enumerate(items):
    if c.get("bottom", {}).get("by_cat"):  # already patched
        continue
    cfg = CFG.get(slug)
    if not cfg:
        continue
    try:
        bfull = B.get_bottom(cfg)
        c["bottom"]["by_cat"] = bfull.get("by_cat", {})
        if c["lead_book"].get("gmb_call"):
            c["lead_book"]["gmb_call"]["by_cat"] = W.call_cat(cfg, "gmb")
        if c["lead_book"].get("gpaid_call"):
            c["lead_book"]["gpaid_call"]["by_cat"] = W.call_cat(cfg, "paid")
        done += 1
        print("[ok %d] %s" % (done, cfg["disp"]), flush=True)
        if done % 5 == 0:
            json.dump(d, open(OUT, "w"), separators=(",", ":"))
    except BaseException as e:
        print("[FAIL] %s: %s" % (cfg.get("disp", slug), type(e).__name__), flush=True)
json.dump(d, open(OUT, "w"), separators=(",", ":"))
print("patched %d clinics" % done)
