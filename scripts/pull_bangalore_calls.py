#!/usr/bin/env python3
"""AI-audited inbound CALL leads for ALL of Bangalore → data_bangalore_calls.json.

Same engine as pull_indiranagar_calls.py but the locality filter is widened to the whole CITY:
any call whose AI-detected city = Bangalore and that hit one of our localities. Per week
(Mon, newest-first, 12wk) × channel × category (STI / SH / MH / Other) + relevant + strong.
channel by dialed number: paid = shared city Google call-asset number; organic = a clinic's own
listing / shared pool number (everything else). Bucketed by CALL time.
Run: AWS_PROFILE=redshift-data python3 scripts/pull_bangalore_calls.py
"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11",
         "2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]
idx = {w: i for i, w in enumerate(WEEKS)}; NW = len(WEEKS)
PAID_NUM = "8045680561"    # Bangalore territory (Google call-asset) number — shared, city-wide
CATS = ["STI", "SH", "MH", "Other"]
CATMAP = {"STI":"STI","SEXUAL_HEALTH_GENERAL":"SH","MENTAL_HEALTH":"MH","OTHER":"Other","NOT_MENTIONED":"Other"}
RELEVANT = ("TALK_TO_DOCTOR","NEEDS_TESTS","BOOK_APPOINTMENT","BOOK_TEST","BOOK_SLOT")

SQL = """SELECT
  TO_CHAR(DATE_TRUNC('week', ec.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') AS wk,
  CASE WHEN RIGHT(ec.exotel_number,10)='{paid}' THEN 'paid' ELSE 'organic' END AS chan,
  COALESCE(ca.analysis.diagnoses.category::varchar,'NOT_MENTIONED') AS cat,
  ca.analysis.user_intent.result::varchar             AS intent,
  ca.analysis.patient_intent_strength.result::varchar AS strength,
  COUNT(*) AS n
FROM allo_analytics.call_analyses ca
JOIN allo_vendors.exotel_calls ec ON ec.call_id = ca.call_id AND ec.routed_to='lead_to_call'
WHERE ca.deleted_at IS NULL AND ca.analysis.user_intent.locality_mentioned.is_our_locality=true
  AND ca.analysis.user_intent.user_city.best_match::varchar='Bangalore'
  AND (ec.start_time + INTERVAL '5 hours 30 minutes') >= '2026-03-23'
GROUP BY 1,2,3,4,5;""".format(paid=PAID_NUM)

def main():
    p = subprocess.run([sys.executable, RQ], input=SQL, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("bangalore calls query failed: " + (p.stderr or "")[:400] + "\n"); sys.exit(1)
    def catblank(): return {c: [0]*NW for c in CATS}
    def chanblank(): return {"total": [0]*NW, "by_cat": catblank()}
    channel = {"paid": chanblank(), "organic": chanblank()}
    total = {"total": [0]*NW, "relevant": [0]*NW, "strong": [0]*NW, "by_cat": catblank(), "relevant_by_cat": catblank()}
    for line in p.stdout.strip().splitlines():
        c = line.split("\t")
        if len(c) < 6: continue
        wk, chan, rawcat, intent, strength, n = c
        if wk not in idx: continue
        try: n = int(float(n))
        except ValueError: continue
        i = idx[wk]; cat = CATMAP.get(rawcat, "Other")
        channel[chan]["total"][i] += n; channel[chan]["by_cat"][cat][i] += n
        total["total"][i] += n; total["by_cat"][cat][i] += n
        if intent in RELEVANT: total["relevant"][i] += n; total["relevant_by_cat"][cat][i] += n
        if strength == "STRONG": total["strong"][i] += n
    out = {"_meta": {"weeks": WEEKS, "city": "Bangalore", "paid_number": PAID_NUM,
            "source": "allo_analytics.call_analyses × exotel_calls(lead_to_call), Bangalore city intent (all localities)",
            "note": "Inbound call leads across ALL Bangalore clinics, attributed by AI caller intent (incl. paid calls). channel: paid=shared city call-asset number, organic=clinic listing/other. category=AI diagnosis. bucketed by call time. CALL VOLUME — does not reconcile to leads/booked."},
        "total": total, "channel": channel}
    json.dump(out, open(os.path.join(ROOT, "data_bangalore_calls.json"), "w"), separators=(",", ":"))
    i = 0
    print("wrote data_bangalore_calls.json")
    print(f"  {WEEKS[i]}: total {total['total'][i]} (paid {channel['paid']['total'][i]} · organic {channel['organic']['total'][i]}) · relevant {total['relevant'][i]}")
    print("  relevant by cat: " + " · ".join(f"{c} {total['relevant_by_cat'][c][i]}" for c in CATS))

if __name__ == "__main__":
    main()
