#!/usr/bin/env python3
"""Unified per-lead attribution for ALL Bangalore clinics — the single source of
truth that reconciles clinic → city. Every lead's clinic = call_location (the
resolved clinic); city = sum of its clinics. By construction, clinic sums to city.

Each lead is bucketed by CHANNEL × MECHANISM (the two capture systems):
  gmb_call    – organic, clinic's own GBP number (PC-Inbound)        [call]
  gmb_web     – organic, Google Business Profile listing → website   [web]
  paid_call   – Google PAID ad, call extension / tracking number     [call]  (manager's "paid (Google call)")
  paid_web    – Google PAID ad → landing page                        [web]
  web_organic – other organic web (clinic page, landing, doctor…)    [web]
  walkin      – walk-in                                              [walk]
  meta        – Facebook / Instagram                                 [web]
  other       – Newspaper / YouTube / Others / Unknown               [mixed]
(Practo is a separate external sheet — added in the funnel, not here.)

tier A = clinic identified at capture (lead_location = clinic code)
tier B = clinic resolved at booking (lead_location = ONLINE / null → call_location set)

Writes data_bangalore_attribution.json {clinics{clinic{bucket:[12wk]}}, city{...}}.
Run: AWS_PROFILE=redshift-data python3 scripts/pull_bangalore_attribution.py
"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKS = ["2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04",
         "2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23"]
idx = {w:i for i,w in enumerate(WEEKS)}; NW=len(WEEKS)
BUCKETS = ["gmb_call","gmb_web","paid_call","paid_web","web_organic","walkin","meta","other"]

SQL = f"""
WITH paid_phones AS (  -- phones that dialed a GOOGLE PAID exotel number (call-asset), by IST week
  SELECT DISTINCT RIGHT(REGEXP_REPLACE(e."from",'[^0-9]',''),10) AS phone,
    DATE_TRUNC('week', e.start_time + INTERVAL '5 hours 30 minutes')::date AS wk
  FROM allo_prod.allo_vendors.exotel_calls e
  JOIN production.csv_uploads.yb_exotel_no_mapping_110226 m
    ON RIGHT(REGEXP_REPLACE(m.exotel_no,'[^0-9]',''),10)=RIGHT(REGEXP_REPLACE(e.exotel_number,'[^0-9]',''),10)
  WHERE m.exotel_source='Google' AND e.start_time >= '{WEEKS[-1]}'
)
SELECT l.call_location AS clinic,
  DATE_TRUNC('week', l.created_on_date)::date AS mon,
  CASE
    -- a PC-Inbound call whose caller phone dialed a Google PAID number that week → Google paid CALL,
    -- even if main_source_wise_leads tagged it Organic (it can't see the dialed number).
    WHEN l.organic_l2='PC-Inbound' AND pp.phone IS NOT NULL       THEN 'paid_call'
    WHEN l.source='Google'  AND l.organic_l2='PC-Inbound'      THEN 'paid_call'
    WHEN l.source='Google'                                     THEN 'paid_web'
    WHEN l.source='Organic' AND l.organic_l2='PC-Inbound'      THEN 'gmb_call'
    WHEN l.source='Organic' AND l.organic_l2='Google Listing'  THEN 'gmb_web'
    WHEN l.organic_l2='Walk In'                                THEN 'walkin'
    WHEN l.source='Organic'                                    THEN 'web_organic'
    WHEN l.source IN ('Fb','Instagram')                        THEN 'meta'
    ELSE 'other'
  END AS bucket,
  -- category, ONLY where attributable: a call (→ categorised by the call-audit, data_indiranagar_calls.json),
  -- or a web landing page / paid campaign that names the condition. Everything else = uncategorised.
  CASE
    WHEN l.organic_l2='PC-Inbound' THEN 'cat_call'
    WHEN l.organic_l2 LIKE 'ED%' OR LOWER(l.google_campaign) LIKE '%\\_ed\\_%' OR LOWER(l.google_campaign) LIKE '%erectile%' THEN 'cat_ed'
    WHEN l.organic_l2 LIKE 'PE%' OR LOWER(l.google_campaign) LIKE '%\\_pe\\_%' THEN 'cat_pe'
    WHEN LOWER(l.google_campaign) LIKE '%std%' OR LOWER(l.google_campaign) LIKE '%sti%' THEN 'cat_sti'
    WHEN LOWER(l.google_campaign) LIKE '%\\_sh\\_%' OR l.organic_l2 LIKE '%Sexual%' THEN 'cat_sh'
    ELSE 'cat_uncat'
  END AS category,
  -- attribution TIMING: was the clinic known at capture, or only set when they booked?
  CASE
    WHEN l.lead_location='ONLINE' OR l.lead_location IS NULL OR pp.phone IS NOT NULL THEN 'tier_resolved'
    ELSE 'tier_captured'
  END AS tier,
  -- sub-split of the web_organic bucket only (clinic page vs a named condition/doctor page vs untagged)
  CASE
    WHEN NOT (l.source='Organic' AND l.organic_l2 NOT IN ('PC-Inbound','Google Listing','Walk In')) THEN 'web_na'
    WHEN l.organic_l2='Clinic Page'                       THEN 'web_clinic'
    WHEN l.organic_l2 IN ('Unknown') OR l.organic_l2 IS NULL THEN 'web_untagged'
    ELSE 'web_page'
  END AS websub,
  COUNT(*) AS n
FROM production.public.main_source_wise_leads l
JOIN allo_prod.allo_health.locations loc
  ON loc.locality=l.call_location AND loc.deleted_at IS NULL AND loc.is_active=1
LEFT JOIN paid_phones pp
  ON pp.phone = RIGHT(REGEXP_REPLACE(l.phone_no1,'[^0-9]',''),10)
  AND pp.wk = DATE_TRUNC('week', l.created_on_date)::date
WHERE loc.city='Bangalore' AND l.created_on_date >= '{WEEKS[-1]}'
GROUP BY 1,2,3,4,5,6 ORDER BY 1,2;
"""
CATS = ["cat_call","cat_ed","cat_pe","cat_sti","cat_sh","cat_uncat"]
TIERS = ["tier_captured","tier_resolved"]
WEBS = ["web_clinic","web_page","web_untagged"]

p = subprocess.run([sys.executable, os.path.join(ROOT,"scripts","redshift_query.py")],
                   input=SQL, capture_output=True, text=True)
if p.returncode != 0 or "ERROR" in (p.stderr or ""):
    sys.stderr.write("query failed: "+(p.stderr or "")[:400]+"\n"); sys.exit(1)

clinics = {}
for line in p.stdout.strip().splitlines():
    c = line.split("\t")
    if len(c) < 7: continue
    clinic, mon, bucket, cat, tier, websub, n = c[0], c[1], c[2], c[3], c[4], c[5], int(float(c[6]))
    if mon not in idx or bucket not in BUCKETS: continue
    o = clinics.setdefault(clinic, {**{b:[0]*NW for b in BUCKETS}, **{k:[0]*NW for k in CATS}, **{k:[0]*NW for k in TIERS}, **{k:[0]*NW for k in WEBS}})
    o[bucket][idx[mon]] += n
    if cat in CATS: o[cat][idx[mon]] += n
    if tier in TIERS: o[tier][idx[mon]] += n
    if websub in WEBS: o[websub][idx[mon]] += n

# totals per clinic + city rollup (city = sum of clinics → reconciles by construction)
city = {**{b:[0]*NW for b in BUCKETS}, **{k:[0]*NW for k in CATS}, **{k:[0]*NW for k in TIERS}, **{k:[0]*NW for k in WEBS}}
for clinic, o in clinics.items():
    o["total"] = [sum(o[b][i] for b in BUCKETS) for i in range(NW)]
    for b in BUCKETS+CATS+TIERS+WEBS:
        for i in range(NW): city[b][i] += o[b][i]
city["total"] = [sum(city[b][i] for b in BUCKETS) for i in range(NW)]

out = {"_meta":{"weeks":WEEKS, "source":"production.public.main_source_wise_leads (clinic=call_location) × locations",
                "buckets":BUCKETS,
                "note":"clinic=call_location (resolved clinic). city=sum of clinics → reconciles. "
                       "gmb_call/gmb_web=organic GBP · paid_call/paid_web=Google ads · web_organic=other organic web · "
                       "walkin · meta=Fb · other=Newspaper/Youtube/Others/Unknown. Practo (external sheet) added in the funnel."},
       "clinics":clinics, "city":city}
json.dump(out, open(os.path.join(ROOT,"data_bangalore_attribution.json"),"w"), separators=(",",":"))

# ---- print reconciliation proof ----
print(f"clinics: {len(clinics)}")
print("\nlatest-week city totals by bucket:")
for b in BUCKETS: print(f"   {b:12} {city[b][0]}")
print(f"   {'TOTAL':12} {city['total'][0]}")
chk = sum(clinics[c]['total'][0] for c in clinics)
print(f"\nRECONCILE latest wk: sum of clinic totals = {chk}  vs  city total = {city['total'][0]}  -> {'OK' if chk==city['total'][0] else 'MISMATCH'}")
print("\nIndiranagar latest week:")
ind = clinics.get("Indiranagar",{})
for b in BUCKETS: print(f"   {b:12} {ind.get(b,[0])[0]}")
print(f"   {'TOTAL':12} {ind.get('total',[0])[0]}")
