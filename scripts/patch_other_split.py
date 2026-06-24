#!/usr/bin/env python3
"""Break the call-audit 'Other' bucket into clusters by AI user_intent, per clinic so it
reconciles with the displayed Other (sum of the 4 sub-buckets == by_cat['Other']):
  condition  — AI tagged a real condition outside STI/SH/MH (category=OTHER)
  consult    — no condition stated, caller wants a doctor/therapist
  service    — no condition stated, needs meds / tests
  unclear    — no condition stated, intent could-not-determine / other
Stored on lead_book.gmb_call.other_split and gpaid_call.other_split.
Resumable (skips calls already carrying other_split). Saves every 5.
Run: AWS_PROFILE=redshift-data python3 scripts/patch_other_split.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import build_clinic_wow as W

ROOT = W.ROOT; OUT = os.path.join(ROOT, "data_source_recon.json")
idx = W.idx; Z = W.Z; LO = W.LO; run_sql = W.run_sql
BUCKETS = ["condition", "consult", "service", "unclear"]

def other_split(cfg, kind):
    if kind == "gmb":
        if not cfg["gmb"]: return None
        where = "RIGHT(ec.exotel_number,10) IN ('%s')" % "','".join(cfg["gmb"]); locf = ""
    else:
        if not cfg["paid"]: return None
        where = "RIGHT(ec.exotel_number,10)='%s'" % cfg["paid"]
        locf = "" if cfg.get("paid_solo") else (
            "AND ca.analysis.user_intent.locality_mentioned.is_our_locality=true "
            "AND ca.analysis.user_intent.locality_mentioned.best_match::varchar='%s'" % cfg["loc"].replace("'", "''"))
    sql = ("SELECT TO_CHAR(DATE_TRUNC('week', ec.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk, "
           "CASE WHEN COALESCE(ca.analysis.diagnoses.category::varchar,'NOT_MENTIONED')='OTHER' THEN 'condition' "
           "  WHEN ca.analysis.user_intent.result::varchar IN ('TALK_TO_DOCTOR','TALK_TO_THERAPIST') THEN 'consult' "
           "  WHEN ca.analysis.user_intent.result::varchar IN ('NEEDS_MEDS','NEEDS_TESTS') THEN 'service' "
           "  ELSE 'unclear' END bucket, COUNT(*) n "
           "FROM allo_analytics.call_analyses ca "
           "JOIN allo_vendors.exotel_calls ec ON ec.call_id=ca.call_id AND ec.routed_to='lead_to_call' AND ec.direction='inbound' "
           "WHERE ca.deleted_at IS NULL AND %s %s AND ec.start_time>='%s' AND ec.start_time<'2026-06-22' "
           "AND COALESCE(ca.analysis.diagnoses.category::varchar,'NOT_MENTIONED') IN ('OTHER','NOT_MENTIONED') "
           "GROUP BY 1,2;" % (where, locf, LO))
    by = {b: Z() for b in BUCKETS}
    for line in run_sql(sql):
        c = line.split("\t")
        if len(c) < 3 or c[0] not in idx or c[1] not in by: continue
        try: by[c[1]][idx[c[0]]] += int(float(c[2]))
        except ValueError: pass
    return by

if __name__ == "__main__":
    d = json.load(open(OUT)); CFG = W.CFG
    items = list(d["clinics"].items()); done = 0
    for slug, c in items:
        lb = c.get("lead_book", {})
        gc, pc = lb.get("gmb_call"), lb.get("gpaid_call")
        if (gc is None or gc.get("other_split")) and (pc is None or pc.get("other_split")):
            continue
        cfg = CFG.get(slug)
        if not cfg: continue
        try:
            if gc is not None and not gc.get("other_split"):
                gc["other_split"] = other_split(cfg, "gmb")
            if pc is not None and not pc.get("other_split"):
                pc["other_split"] = other_split(cfg, "paid")
            done += 1
            print("[ok %d/%d] %s" % (done, len(items), cfg["disp"]), flush=True)
            if done % 5 == 0:
                json.dump(d, open(OUT, "w"), separators=(",", ":"))
        except BaseException as e:
            print("[FAIL] %s: %s" % (cfg.get("disp", slug), type(e).__name__), flush=True)
    json.dump(d, open(OUT, "w"), separators=(",", ":"))
    print("patched %d clinics" % done)
