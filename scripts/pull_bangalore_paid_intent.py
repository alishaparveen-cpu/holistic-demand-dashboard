#!/usr/bin/env python3
"""Resolve the Google-PAID-CALL leak by CALLER INTENT → data_bangalore_paid_intent.json.

Today a paid call only gets a clinic if the caller BOOKS (call_location). But the AI call-audit
already detects which clinic the caller WANTED (user_intent.locality_mentioned.best_match), booking
or not. This pull attributes every paid call (to the shared city number 8045680561, routed_to=
lead_to_call) to that clinic-of-intent — recovering most of the leak.

Per clinic (the 14 funnel clinics) + residual (no clinic-of-intent: city-only / no-geo / non-funnel
locality) + total, weekly (Mon, newest-first, 12 wk). CALL VOLUME (intent), not booking-resolved
leads — a parallel layer, does not merge into the 316 spine.
Run: AWS_PROFILE=redshift-data python3 scripts/pull_bangalore_paid_intent.py
"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11",
         "2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]
idx = {w:i for i,w in enumerate(WEEKS)}; NW=len(WEEKS)
PAID_NUM = "8045680561"
CLINICS = ["Arekere","Bellandur","Brookefield","Electronic City","HSR Layout","Indiranagar",
           "Jayanagar","KR Puram","Kengeri","Koramangala","RT Nagar","Sahakara Nagar","Vijayanagar","Whitefield"]
_in = ",".join("'%s'" % c.replace("'", "''") for c in CLINICS)

SQL = """SELECT
  TO_CHAR(DATE_TRUNC('week', ec.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk,
  CASE WHEN ca.analysis.user_intent.locality_mentioned.is_our_locality=true
            AND ca.analysis.user_intent.locality_mentioned.best_match::varchar IN ({clinics})
       THEN ca.analysis.user_intent.locality_mentioned.best_match::varchar
       ELSE 'residual' END AS bucket,
  COUNT(*) n
FROM allo_analytics.call_analyses ca
JOIN allo_vendors.exotel_calls ec ON ec.call_id=ca.call_id AND ec.routed_to='lead_to_call'
WHERE ca.deleted_at IS NULL AND RIGHT(ec.exotel_number,10)='{paid}'
  AND (ec.start_time + INTERVAL '5 hours 30 minutes') >= '2026-03-30'
GROUP BY 1,2 ORDER BY 1,2;""".format(clinics=_in, paid=PAID_NUM)

p = subprocess.run([sys.executable, RQ], input=SQL, capture_output=True, text=True)
if p.returncode != 0 or "ERROR" in (p.stderr or ""):
    sys.stderr.write("paid-intent query failed: " + (p.stderr or "")[:400] + "\n"); sys.exit(1)

clinics = {c: [0]*NW for c in CLINICS}
residual = [0]*NW
for line in p.stdout.strip().splitlines():
    c = line.split("\t")
    if len(c) < 3 or c[0] not in idx: continue
    wk, bucket, n = c[0], c[1], int(float(c[2])); i = idx[wk]
    if bucket in clinics: clinics[bucket][i] += n
    else: residual[i] += n
total = [sum(clinics[c][i] for c in CLINICS) + residual[i] for i in range(NW)]
attributed = [sum(clinics[c][i] for c in CLINICS) for i in range(NW)]

out = {"_meta": {"weeks": WEEKS, "city": "Bangalore", "paid_number": PAID_NUM, "clinics": CLINICS,
        "source": "allo_analytics.call_analyses × exotel_calls(lead_to_call, #8045680561), attributed by user_intent.locality_mentioned.best_match",
        "note": "Google PAID-CALL volume attributed to the clinic the caller WANTED (intent), booking or not — recovers the leak. residual = no clinic-of-intent (city-only / no-geo / non-funnel locality). CALL VOLUME, not booking-resolved leads; parallel layer, does NOT merge into the 316 spine."},
    "clinics": clinics, "residual": residual, "total": total}
json.dump(out, open(os.path.join(ROOT, "data_bangalore_paid_intent.json"), "w"), separators=(",", ":"))
print("wrote data_bangalore_paid_intent.json")
for i in range(6):
    share = round(attributed[i]/total[i]*100) if total[i] else 0
    print(f"  {WEEKS[i]}: total {total[i]} = clinic-intent {attributed[i]} ({share}%) + residual {residual[i]}")
print("  latest-wk by clinic: " + " · ".join(f"{c.split()[0]} {clinics[c][0]}" for c in CLINICS if clinics[c][0]))
