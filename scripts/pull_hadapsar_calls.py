#!/usr/bin/env python3
"""AI-audited inbound CALL leads for Pune|Hadapsar → data_hadapsar_calls.json.

Two channels:
  GMB (2241483789) — clinic-direct. DND total = 2× Exotel total (confirmed match).
    • raw.*: ALL calls from allo_vendors.exotel_calls (total/unique/answered/missed).
    • gmb_ai.*: AI category (STI/SH/MH/Other) from call_analyses for GMB calls.

  Paid city (2048556242) — shared Pune call-asset.
    • paid_ai.*: calls where AI says caller mentioned Hadapsar (locality_mentioned = 'Hadapsar').

Run: AWS_PROFILE=redshift-data python3 scripts/pull_hadapsar_calls.py
"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11",
         "2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]
idx = {w: i for i, w in enumerate(WEEKS)}; NW = len(WEEKS)
GMB_NUM  = "2241483789"   # Hadapsar GMB listing — clinic-direct (DND confirmed)
PAID_NUM = "2048556242"   # Pune city paid call-asset
CATS = ["STI", "SH", "MH", "Other"]
CATMAP = {"STI":"STI","SEXUAL_HEALTH_GENERAL":"SH","MENTAL_HEALTH":"MH",
          "OTHER":"Other","NOT_MENTIONED":"Other"}
RELEVANT = ("TALK_TO_DOCTOR","NEEDS_TESTS","BOOK_APPOINTMENT","BOOK_TEST","BOOK_SLOT")

SQL_RAW = """
SELECT
  TO_CHAR(DATE_TRUNC('week', ec.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') AS wk,
  COUNT(*)                                                                AS total_calls,
  COUNT(DISTINCT RIGHT(COALESCE(ec."from",''),10))                       AS unique_callers,
  SUM(CASE WHEN ec.status = 'completed' THEN 1 ELSE 0 END)              AS answered,
  SUM(CASE WHEN ec.status != 'completed' THEN 1 ELSE 0 END)             AS missed
FROM allo_vendors.exotel_calls ec
WHERE RIGHT(ec.exotel_number,10) = '{gmb}'
  AND ec.routed_to = 'lead_to_call'
  AND (ec.start_time + INTERVAL '5 hours 30 minutes') >= '2026-03-16'
GROUP BY 1 ORDER BY 1 DESC;
""".format(gmb=GMB_NUM)

SQL_GMB_AI = """
SELECT
  TO_CHAR(DATE_TRUNC('week', ec.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') AS wk,
  COALESCE(ca.analysis.diagnoses.category::varchar,'NOT_MENTIONED') AS cat,
  ca.analysis.user_intent.result::varchar                            AS intent,
  ca.analysis.patient_intent_strength.result::varchar                AS strength,
  COUNT(*)                                                           AS n
FROM allo_analytics.call_analyses ca
JOIN allo_vendors.exotel_calls ec ON ec.call_id = ca.call_id
  AND ec.routed_to = 'lead_to_call'
WHERE ca.deleted_at IS NULL
  AND RIGHT(ec.exotel_number,10) = '{gmb}'
  AND (ec.start_time + INTERVAL '5 hours 30 minutes') >= '2026-03-16'
GROUP BY 1,2,3,4 ORDER BY 1 DESC;
""".format(gmb=GMB_NUM)

SQL_PAID_AI = """
SELECT
  TO_CHAR(DATE_TRUNC('week', ec.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') AS wk,
  COALESCE(ca.analysis.diagnoses.category::varchar,'NOT_MENTIONED') AS cat,
  ca.analysis.user_intent.result::varchar                            AS intent,
  COUNT(*)                                                           AS n
FROM allo_analytics.call_analyses ca
JOIN allo_vendors.exotel_calls ec ON ec.call_id = ca.call_id
  AND ec.routed_to = 'lead_to_call'
WHERE ca.deleted_at IS NULL
  AND RIGHT(ec.exotel_number,10) = '{paid}'
  AND ca.analysis.user_intent.locality_mentioned.is_our_locality = true
  AND ca.analysis.user_intent.user_city.best_match::varchar = 'Pune'
  AND ca.analysis.user_intent.locality_mentioned.best_match::varchar = 'Hadapsar'
  AND (ec.start_time + INTERVAL '5 hours 30 minutes') >= '2026-03-16'
GROUP BY 1,2,3 ORDER BY 1 DESC;
""".format(paid=PAID_NUM)

def run_sql(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("query failed: " + (p.stderr or "")[:500] + "\n"); sys.exit(1)
    return p.stdout.strip().splitlines()

def blank_ai():
    return {"total": [0]*NW, "relevant": [0]*NW, "strong": [0]*NW,
            "by_cat": {c: [0]*NW for c in CATS}}

def main():
    Z = [0]*NW

    raw = {"total": list(Z), "unique": list(Z), "answered": list(Z), "missed": list(Z)}
    for line in run_sql(SQL_RAW):
        c = line.split("\t")
        if len(c) < 5 or c[0] not in idx: continue
        i = idx[c[0]]
        try:
            raw["total"][i]    = int(float(c[1]))
            raw["unique"][i]   = int(float(c[2]))
            raw["answered"][i] = int(float(c[3]))
            raw["missed"][i]   = int(float(c[4]))
        except ValueError: pass

    gmb_ai = blank_ai()
    for line in run_sql(SQL_GMB_AI):
        c = line.split("\t")
        if len(c) < 5 or c[0] not in idx: continue
        wk, rawcat, intent, strength, n_s = c
        try: n = int(float(n_s))
        except ValueError: continue
        i = idx[wk]; cat = CATMAP.get(rawcat, "Other")
        gmb_ai["total"][i]        += n
        gmb_ai["by_cat"][cat][i]  += n
        if intent in RELEVANT:
            gmb_ai["relevant"][i] += n
        if strength == "STRONG":
            gmb_ai["strong"][i]   += n

    paid_ai = blank_ai()
    for line in run_sql(SQL_PAID_AI):
        c = line.split("\t")
        if len(c) < 4 or c[0] not in idx: continue
        wk, rawcat, intent, n_s = c
        try: n = int(float(n_s))
        except ValueError: continue
        i = idx[wk]; cat = CATMAP.get(rawcat, "Other")
        paid_ai["total"][i]        += n
        paid_ai["by_cat"][cat][i]  += n
        if intent in RELEVANT:
            paid_ai["relevant"][i] += n

    out = {
        "_meta": {
            "weeks": WEEKS, "clinic": "Pune|Hadapsar",
            "gmb_number": GMB_NUM, "paid_number": PAID_NUM,
            "source": "allo_vendors.exotel_calls (raw volume) + allo_analytics.call_analyses (AI category)",
            "note": (
                "raw = ALL inbound calls to GMB number (2241483789) from Exotel. "
                "DND dashboard total = 2× Exotel total (confirmed match). "
                "gmb_ai = AI-audited subset of GMB calls (category). "
                "paid_ai = paid number (2048556242) calls where AI says caller mentioned Hadapsar."
            ),
        },
        "raw":     raw,
        "gmb_ai":  gmb_ai,
        "paid_ai": paid_ai,
        "ai":      gmb_ai,
    }
    json.dump(out, open(os.path.join(ROOT, "data_hadapsar_calls.json"), "w"), separators=(",", ":"))

    i = 0; wk = WEEKS[i]
    print(f"wrote data_hadapsar_calls.json — {wk}:")
    print(f"  raw:     total={raw['total'][i]} unique={raw['unique'][i]} answered={raw['answered'][i]} missed={raw['missed'][i]}")
    print(f"  gmb_ai:  audited={gmb_ai['total'][i]} relevant={gmb_ai['relevant'][i]} | " +
          " ".join(f"{c}={gmb_ai['by_cat'][c][i]}" for c in CATS))
    print(f"  paid_ai: total={paid_ai['total'][i]} | " +
          " ".join(f"{c}={paid_ai['by_cat'][c][i]}" for c in CATS))

if __name__ == "__main__":
    main()
