#!/usr/bin/env python3
"""AI-audited inbound CALL leads for Bangalore|Indiranagar → data_indiranagar_calls.json.

Methodology matches the GMB DND dashboard:
  • GMB number (8047160881) = Indiranagar clinic direct.  Number itself identifies clinic,
    so every call to this number is attributed to Indiranagar — no AI locality inference needed.
  • Paid/pool number (8045680561) = city-level only, NOT attributed to specific clinics here.

Two SQL passes for the GMB number:
  1. Raw volume from exotel_calls (total / unique callers / answered / missed) — matches DND dashboard.
  2. AI category from call_analyses × exotel_calls for audited answered calls (STI/SH/MH/Other).
     Category is AI-inferred caller intent from audio; only answered calls that got audited have it.

Run: AWS_PROFILE=redshift-data python3 scripts/pull_indiranagar_calls.py
"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04",
         "2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23"]
idx = {w: i for i, w in enumerate(WEEKS)}; NW = len(WEEKS)
GMB_NUM  = "8047160881"    # Indiranagar clinic GMB listing number — clinic-direct
CATS = ["STI", "SH", "MH", "Other"]
CATMAP = {"STI":"STI","SEXUAL_HEALTH_GENERAL":"SH","MENTAL_HEALTH":"MH","OTHER":"Other","NOT_MENTIONED":"Other"}
RELEVANT = ("TALK_TO_DOCTOR","NEEDS_TESTS","BOOK_APPOINTMENT","BOOK_TEST","BOOK_SLOT")

# ── Query 1: raw call volume from Exotel (no AI required — matches DND dashboard) ──
SQL_RAW = """SELECT
  TO_CHAR(DATE_TRUNC('week', ec.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') AS wk,
  COUNT(*)                                                               AS total_calls,
  COUNT(DISTINCT RIGHT(COALESCE(ec.from_number,''),10))                 AS unique_callers,
  SUM(CASE WHEN ec.call_status IN ('completed','answered') THEN 1 ELSE 0 END) AS answered_calls,
  SUM(CASE WHEN ec.call_status IN ('no-answer','busy','missed','failed') THEN 1 ELSE 0 END) AS missed_calls
FROM allo_vendors.exotel_calls ec
WHERE RIGHT(ec.exotel_number,10)='{gmb}'
  AND ec.routed_to='lead_to_call'
  AND (ec.start_time + INTERVAL '5 hours 30 minutes') >= '2026-03-16'
GROUP BY 1
ORDER BY 1 DESC;""".format(gmb=GMB_NUM)

# ── Query 2: AI category for audited GMB calls ──
SQL_CAT = """SELECT
  TO_CHAR(DATE_TRUNC('week', ec.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') AS wk,
  COALESCE(ca.analysis.diagnoses.category::varchar,'NOT_MENTIONED')     AS cat,
  ca.analysis.user_intent.result::varchar                                AS intent,
  ca.analysis.patient_intent_strength.result::varchar                   AS strength,
  COUNT(*)                                                               AS n
FROM allo_analytics.call_analyses ca
JOIN allo_vendors.exotel_calls ec ON ec.call_id = ca.call_id
  AND ec.routed_to='lead_to_call'
WHERE ca.deleted_at IS NULL
  AND RIGHT(ec.exotel_number,10)='{gmb}'
  AND (ec.start_time + INTERVAL '5 hours 30 minutes') >= '2026-03-16'
GROUP BY 1,2,3,4;""".format(gmb=GMB_NUM)

def run_sql(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("query failed: " + (p.stderr or "")[:400] + "\n"); sys.exit(1)
    return p.stdout.strip().splitlines()

def main():
    Z = [0]*NW

    # ── Pass 1: raw volume ──
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

    # ── Pass 2: AI categories ──
    def catblank(): return {c: list(Z) for c in CATS}
    ai = {"total": list(Z), "relevant": list(Z), "strong": list(Z),
          "by_cat": catblank(), "relevant_by_cat": catblank()}
    for line in run_sql(SQL_CAT):
        c = line.split("\t")
        if len(c) < 5 or c[0] not in idx: continue
        wk, rawcat, intent, strength, n_s = c
        try: n = int(float(n_s))
        except ValueError: continue
        i = idx[wk]; cat = CATMAP.get(rawcat, "Other")
        ai["total"][i]           += n
        ai["by_cat"][cat][i]     += n
        if intent in RELEVANT:
            ai["relevant"][i]              += n
            ai["relevant_by_cat"][cat][i]  += n
        if strength == "STRONG":
            ai["strong"][i] += n

    out = {
        "_meta": {
            "weeks": WEEKS, "clinic": "Bangalore|Indiranagar", "gmb_number": GMB_NUM,
            "source": "allo_vendors.exotel_calls (volume) + allo_analytics.call_analyses (category)",
            "note": (
                "Volume (raw.*) = ALL calls to the GMB listing number including missed — "
                "matches GMB DND dashboard. "
                "AI category (ai.*) = audited answered calls only; category = AI-inferred caller intent. "
                "Paid/pool city number NOT included here — remains city-level, not clinic-attributed."
            ),
        },
        "raw": raw,   # total / unique / answered / missed — Exotel ground truth
        "ai":  ai,    # AI-audited subset: total audited, relevant, strong, by_cat
    }
    json.dump(out, open(os.path.join(ROOT, "data_indiranagar_calls.json"), "w"), separators=(",", ":"))

    i = 0
    wk = WEEKS[i]
    print("wrote data_indiranagar_calls.json")
    print(f"  {wk}: raw total={raw['total'][i]} unique={raw['unique'][i]} answered={raw['answered'][i]} missed={raw['missed'][i]}")
    print(f"  {wk}: AI audited={ai['total'][i]} relevant={ai['relevant'][i]}")
    print(f"  {wk}: by cat: " + " · ".join(f"{c}={ai['by_cat'][c][i]}" for c in CATS))

if __name__ == "__main__":
    main()
