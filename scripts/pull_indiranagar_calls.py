#!/usr/bin/env python3
"""AI-audited inbound CALL leads for Bangalore|Indiranagar → data_indiranagar_calls.json.

From allo_analytics.call_analyses × exotel_calls (routed_to='lead_to_call'), the AI gives each
call: the clinic the caller wanted (locality intent → keeps Indiranagar), the diagnosis category,
and intent strength. We additionally split by the NUMBER dialed (exotel_number):
  • paid  = the city Google call-asset number (territory) — paid Google calls
  • gmb   = the clinic's own Google-Business-listing number — GMB organic calls
  • other = a shared / other-clinic number, AI-attributed to Indiranagar by caller intent
Per week (Mon, newest-first, 12 wk) × channel × category (STI / SH / MH / Other) + relevant + strong.
Bucketed by CALL time. Run: AWS_PROFILE=redshift-data python3 scripts/pull_indiranagar_calls.py
"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04",
         "2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23"]
idx = {w: i for i, w in enumerate(WEEKS)}; NW = len(WEEKS)
PAID_NUM = "8045680561"    # Bangalore territory (Google call-asset) number
GMB_NUM  = "8047160881"    # Indiranagar clinic GMB listing number
CATS = ["STI", "SH", "MH", "Other"]
CATMAP = {"STI":"STI","SEXUAL_HEALTH_GENERAL":"SH","MENTAL_HEALTH":"MH","OTHER":"Other","NOT_MENTIONED":"Other"}
RELEVANT = ("TALK_TO_DOCTOR","NEEDS_TESTS","BOOK_APPOINTMENT","BOOK_TEST","BOOK_SLOT")

SQL = """SELECT
  TO_CHAR(DATE_TRUNC('week', ec.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') AS wk,
  CASE WHEN RIGHT(ec.exotel_number,10)='{paid}' THEN 'paid'
       WHEN RIGHT(ec.exotel_number,10)='{gmb}'  THEN 'gmb'
       ELSE 'other' END AS chan,
  COALESCE(ca.analysis.diagnoses.category::varchar,'NOT_MENTIONED') AS cat,
  ca.analysis.user_intent.result::varchar           AS intent,
  ca.analysis.patient_intent_strength.result::varchar AS strength,
  COUNT(*) AS n
FROM allo_analytics.call_analyses ca
JOIN allo_vendors.exotel_calls ec ON ec.call_id = ca.call_id AND ec.routed_to='lead_to_call'
WHERE ca.deleted_at IS NULL AND ca.analysis.user_intent.locality_mentioned.is_our_locality=true
  AND ca.analysis.user_intent.user_city.best_match::varchar='Bangalore'
  AND ca.analysis.user_intent.locality_mentioned.best_match::varchar='Indiranagar'
  AND (ec.start_time + INTERVAL '5 hours 30 minutes') >= '2026-03-16'
GROUP BY 1,2,3,4,5;""".format(paid=PAID_NUM, gmb=GMB_NUM)

def main():
    p = subprocess.run([sys.executable, RQ], input=SQL, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("indiranagar calls query failed: " + (p.stderr or "")[:400] + "\n"); sys.exit(1)
    def catblank(): return {c: [0]*NW for c in CATS}
    def chanblank(): return {"total": [0]*NW, "by_cat": catblank()}
    channel = {"paid": chanblank(), "gmb": chanblank(), "other": chanblank()}
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
    out = {"_meta": {"weeks": WEEKS, "clinic": "Bangalore|Indiranagar", "paid_number": PAID_NUM, "gmb_number": GMB_NUM,
            "source": "allo_analytics.call_analyses × exotel_calls(lead_to_call), Indiranagar locality intent",
            "note": "Inbound call leads, clinic-attributed by AI caller intent (incl. paid calls). channel by dialed number: paid=city call-asset, gmb=clinic listing, other=shared/other pool. category=AI diagnosis (STI/SH/MH/Other). bucketed by call time."},
        "total": total, "channel": channel}
    json.dump(out, open(os.path.join(ROOT, "data_indiranagar_calls.json"), "w"), separators=(",", ":"))
    i = 0
    print("wrote data_indiranagar_calls.json")
    print(f"  {WEEKS[i]}: total {total['total'][i]} (paid {channel['paid']['total'][i]} · gmb {channel['gmb']['total'][i]} · other {channel['other']['total'][i]}) · relevant {total['relevant'][i]}")
    print(f"  by cat: " + " · ".join(f"{c} {total['by_cat'][c][i]}" for c in CATS))

if __name__ == "__main__":
    main()
