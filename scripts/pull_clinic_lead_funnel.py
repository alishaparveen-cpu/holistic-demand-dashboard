#!/usr/bin/env python3
"""Pull CLINIC-LEVEL leads from the AI call audit → data_clinic_lead_funnel.json.
The clinic tag on an inbound lead comes from the call-audit locality
(allo_analytics.call_analyses · analysis.user_intent.locality_mentioned.best_match,
is_our_locality=true), joined to the inbound lead calls (allo_vendors.exotel_calls,
routed_to='lead_to_call'). This is the foundation the manager asked for: all
clinic-level leads → relevant leads (clinic-specific). Category split is kept for the
next (level-2) layer.

Per "City|Clinic" × week (newest-first, dashboard weeks — only weeks since 27 May have audit data):
  lead_calls = inbound lead calls the AI placed at this clinic
  relevant   = of those, intent is to use the service (TALK_TO_DOCTOR / NEEDS_TESTS / BOOK_*)
  strong     = patient_intent_strength = STRONG
  by_cat     = lead_calls split by diagnoses.category (STI / SEXUAL_HEALTH_GENERAL / MENTAL_HEALTH / OTHER / NOT_MENTIONED)
Run:  AWS_PROFILE=redshift-data python3 scripts/pull_clinic_lead_funnel.py
"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04",
         "2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23","2026-03-16"]
idx = {w: i for i, w in enumerate(WEEKS)}; NW = len(WEEKS)
CATS = ["STI", "SEXUAL_HEALTH_GENERAL", "MENTAL_HEALTH", "OTHER", "NOT_MENTIONED"]
RELEVANT_INTENT = ("TALK_TO_DOCTOR", "NEEDS_TESTS", "BOOK_APPOINTMENT", "BOOK_TEST", "BOOK_SLOT")

SQL = """SELECT
  TO_CHAR(DATE_TRUNC('week', ca.created_at + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') AS wk,
  ca.analysis.user_intent.user_city.best_match::varchar          AS city,
  ca.analysis.user_intent.locality_mentioned.best_match::varchar AS loc,
  COALESCE(ca.analysis.diagnoses.category::varchar,'NOT_MENTIONED') AS cat,
  ca.analysis.user_intent.result::varchar                        AS intent,
  ca.analysis.patient_intent_strength.result::varchar            AS strength,
  COUNT(*) AS n
FROM allo_analytics.call_analyses ca
JOIN allo_vendors.exotel_calls ec ON ec.call_id = ca.call_id AND ec.routed_to='lead_to_call'
WHERE ca.deleted_at IS NULL
  AND ca.analysis.user_intent.locality_mentioned.is_our_locality = true
  AND (ca.created_at + INTERVAL '5 hours 30 minutes') >= '2026-05-25'
GROUP BY 1,2,3,4,5,6 ORDER BY 1,2,3;"""

# locality (audit) → clinic locality (dashboard key) where the AI name differs from our clinic key
LOC_FIX = {}


def main():
    p = subprocess.run([sys.executable, RQ], input=SQL, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("call-funnel query failed: " + (p.stderr or "")[:500] + "\n"); sys.exit(1)
    D = {}
    def blank():
        return {"lead_calls": [0]*NW, "relevant": [0]*NW, "strong": [0]*NW,
                "by_cat": {c: [0]*NW for c in CATS}}
    for line in p.stdout.strip().splitlines():
        c = line.split("\t")
        if len(c) < 7: continue
        wk, city, loc, cat, intent, strength, n = c
        if wk not in idx or not city or not loc: continue
        loc = LOC_FIX.get(loc, loc)
        if cat not in CATS: cat = "NOT_MENTIONED"
        try: n = int(float(n))
        except ValueError: continue
        key = f"{city}|{loc}"; i = idx[wk]
        o = D.setdefault(key, blank())
        o["lead_calls"][i] += n
        o["by_cat"][cat][i] += n
        if intent in RELEVANT_INTENT: o["relevant"][i] += n
        if strength == "STRONG": o["strong"][i] += n

    out = {"_meta": {"weeks": WEEKS,
                     "source": "allo_analytics.call_analyses (AI call audit) × exotel_calls(lead_to_call) — clinic tag from audit locality",
                     "available_from": "2026-05-27 (audit start) — earlier weeks are 0",
                     "fields": "lead_calls=inbound lead calls placed at this clinic by the AI locality; relevant=service-intent; strong=STRONG intent; by_cat=diagnosis category (level-2 layer)"}}
    out.update(D)
    json.dump(out, open(os.path.join(ROOT, "data_clinic_lead_funnel.json"), "w"), separators=(",", ":"))
    w_full = idx["2026-06-01"]
    tot = sum(o["lead_calls"][w_full] for o in D.values())
    rel = sum(o["relevant"][w_full] for o in D.values())
    print(f"data_clinic_lead_funnel.json · {len(D)} clinics · week 1-7 Jun: {tot} clinic lead-calls · {rel} relevant")
    for k, o in sorted(D.items(), key=lambda kv: -kv[1]["lead_calls"][w_full])[:6]:
        print(f"  {k:30} lead_calls {o['lead_calls'][w_full]:3} · relevant {o['relevant'][w_full]:3} · strong {o['strong'][w_full]:3}")


if __name__ == "__main__":
    main()
