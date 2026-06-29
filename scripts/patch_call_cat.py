#!/usr/bin/env python3
"""Re-run the AI-audit call category split as UNIQUE PATIENTS per category (not COUNT(*) of
all calls) and overwrite lead_book.gmb_call.by_cat / gpaid_call.by_cat in data_source_recon.
Imports the (now fixed) call_cat from build_clinic_wow. Resumable-safe (idempotent)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import build_clinic_wow as W
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data_source_recon.json")
d = json.load(open(OUT)); CFG = W.CFG
ok = 0
for slug, c in d["clinics"].items():
    cfg = CFG.get(slug)
    if not cfg: continue
    lb = c.get("lead_book", {}); chg = False
    try:
        if lb.get("gmb_call") is not None and cfg.get("gmb"):
            bc = W.call_cat(cfg, "gmb")
            if bc: lb["gmb_call"]["by_cat"] = bc; chg = True
        if lb.get("gpaid_call") is not None and cfg.get("paid"):
            bc = W.call_cat(cfg, "paid")
            if bc: lb["gpaid_call"]["by_cat"] = bc; chg = True
    except Exception as e:
        print("  [warn] %s: %s" % (cfg.get("disp", slug), str(e)[:80])); continue
    if chg: ok += 1; print("[ok %d] %s" % (ok, cfg.get("disp", slug)), flush=True)
json.dump(d, open(OUT, "w"), separators=(",", ":"))
print("patched by_cat (UNIQUE patients) for %d clinics" % ok)
