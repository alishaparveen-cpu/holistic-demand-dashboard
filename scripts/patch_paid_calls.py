#!/usr/bin/env python3
"""Re-pull the Google paid-call audit funnel for clinics that just got a paid-call
forwarding number added to the config (cities that were missing it). Updates
lead_book.gpaid_call (+ by_cat). Resumable (skips clinics that already have data).
Run: AWS_PROFILE=redshift-data python3 scripts/patch_paid_calls.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import build_clinic_wow as W
import build_source_recon as SR
OUT = os.path.join(W.ROOT, "data_source_recon.json")

if __name__ == "__main__":
    d = json.load(open(OUT)); CFG = W.CFG; done = 0; targets = []
    for slug, c in d["clinics"].items():
        cfg = CFG.get(slug)
        if not cfg or not cfg.get("paid"): continue
        gp = (c.get("lead_book", {}) or {}).get("gpaid_call")
        if gp and gp.get("total") and any(gp["total"]): continue   # already has paid-call data
        targets.append(slug)
    print("re-pulling paid calls for %d clinics" % len(targets), flush=True)
    for slug in targets:
        cfg = CFG[slug]
        try:
            paid_lb = SR.call_funnel(cfg, "paid")
            if paid_lb is not None: paid_lb["by_cat"] = W.call_cat(cfg, "paid")
            d["clinics"][slug].setdefault("lead_book", {})["gpaid_call"] = paid_lb
            done += 1
            tot = sum((paid_lb or {}).get("total", []) or [])
            print("[ok %d/%d] %s  paid-call leads=%d" % (done, len(targets), cfg["disp"], tot), flush=True)
            if done % 4 == 0: json.dump(d, open(OUT, "w"), separators=(",", ":"))
        except BaseException as e:
            print("[FAIL] %s: %s" % (cfg.get("disp", slug), type(e).__name__), flush=True)
    json.dump(d, open(OUT, "w"), separators=(",", ":"))
    print("PAIDCALLS_DONE patched %d" % done, flush=True)
