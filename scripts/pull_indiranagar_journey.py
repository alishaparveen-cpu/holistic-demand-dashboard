#!/usr/bin/env python3
"""Exact 'how they came' journey for Indiranagar leads, from
production.public.main_source_wise_leads. For every attribution bucket it lists
the EXACT entry path (inbound call / GMB listing / specific landing page /
named Google-paid campaign / Meta campaign / walk-in / newspaper / etc.),
per week, aligned to the funnel's 12 Monday-weeks.

Writes:
  data_indiranagar_journey.json    — paths[] grouped by bucket, weekly arrays
  data_indiranagar_attribution.json — bucket totals (regenerated from the SAME
                                      query so the two never drift)

A lead is placed in the week of its CREATION (created_on_date), not its booking
week. ~88% of Indiranagar leads book same-day, so the lead-week ≈ booking-week
for almost all; the funnel's cohort toggle realigns the tail.

Run: AWS_PROFILE=redshift-data python3 scripts/pull_indiranagar_journey.py
"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Funnel's canonical 12 Monday-weeks (newest first) — must match data_indiranagar.json
WEEKS = ["2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04",
         "2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23"]
idx = {w: i for i, w in enumerate(WEEKS)}
NW = len(WEEKS)

SQL = """
WITH lead_utm AS (
  SELECT
    RIGHT(REGEXP_REPLACE(phone_no,'[^0-9]',''),10) AS phone10,
    DATE_TRUNC('week', created_at + INTERVAL '5 hours 30 minutes')::date AS wk_mon,
    MAX(utm_source)   AS utm_source,
    MAX(utm_medium)   AS utm_medium,
    MAX(utm_campaign) AS utm_campaign
  FROM allo_persons.lead
  WHERE created_at >= '{start}'
  GROUP BY 1, 2
)
SELECT
  DATE_TRUNC('week', msw.created_on_date)::date AS mon,
  -- attribution bucket --
  CASE
    WHEN msw.organic_l2 = 'Walk In' THEN 'walkin'
    WHEN msw.source = 'Organic' AND msw.lead_location = 'BLR_80FT' AND msw.organic_l2 IN ('PC-Inbound','Google Listing') THEN 'gmb_direct'
    -- GMB → WhatsApp: patient tapped WhatsApp button on GMB listing (utm=gmb/whatsapp)
    WHEN msw.source = 'Organic' AND lu.utm_source='gmb' AND lu.utm_medium='whatsapp' THEN 'gmb_direct'
    WHEN msw.source IN ('Fb','Newspaper','Youtube') AND msw.organic_l2 IN ('PC-Inbound','Google Listing') THEN 'other'
    WHEN msw.source = 'Google' THEN 'google_paid'
    -- Practo CRM leads: utm_source=practo in allo_persons.lead (retool entry or Practo app)
    WHEN lu.utm_source = 'practo' THEN 'practo_crm'
    -- CRM outbound WhatsApp re-engagement
    WHEN lu.utm_medium = 'whatsapp' AND lu.utm_campaign = 'outbound' THEN 'outbound_wa'
    WHEN msw.lead_location = 'BLR_80FT' OR msw.organic_l2 = 'Clinic Page' THEN 'onsite_web'
    WHEN msw.lead_location = 'ONLINE' THEN 'online_booking'
    WHEN msw.lead_location IS NOT NULL AND msw.lead_location NOT IN ('BLR_80FT','ONLINE') THEN 'misattrib'
    ELSE 'other'
  END AS bucket,
  -- EXACT entry path (how they actually came) --
  CASE
    WHEN msw.source = 'Google'    THEN 'Google paid · ' || COALESCE(NULLIF(msw.google_campaign,''),'(unnamed campaign)')
    WHEN msw.source = 'Fb'        THEN 'Meta · '        || COALESCE(NULLIF(msw.fb_campaign,''),'(unnamed campaign)')
    WHEN msw.source = 'Newspaper' THEN 'Newspaper'
    WHEN msw.source = 'Youtube'   THEN 'YouTube'
    WHEN msw.organic_l2 = 'PC-Inbound'     THEN 'Inbound call (clinic number)'
    WHEN msw.organic_l2 = 'Google Listing' THEN 'GMB listing → website (clicked profile link)'
    WHEN lu.utm_source='gmb' AND lu.utm_medium='whatsapp' THEN 'GMB listing → WhatsApp (tapped chat button)'
    WHEN lu.utm_source = 'practo' AND lu.utm_medium LIKE '%retool%' THEN 'Practo (staff entered via retool)'
    WHEN lu.utm_source = 'practo' THEN 'Practo (app booking or Appointments page)'
    WHEN lu.utm_medium = 'whatsapp' AND lu.utm_campaign = 'outbound' THEN 'CRM outbound WhatsApp (re-engagement)'
    WHEN msw.organic_l2 = 'Walk In'        THEN 'Walk-in'
    WHEN msw.organic_l2 LIKE '%Page%'      THEN 'Landing — ' || msw.organic_l2
    WHEN msw.organic_l2 = 'Doctor'         THEN 'Web — doctor page'
    WHEN msw.organic_l2 = 'Sexologist'     THEN 'Web — sexologist page'
    WHEN msw.source = 'Others'             THEN 'Others (opaque CRM tag)'
    WHEN msw.organic_l2 IN ('Unknown') OR msw.organic_l2 IS NULL THEN 'Unknown / untagged'
    ELSE COALESCE(msw.organic_l2,'Other')
  END AS path,
  msw.source AS channel,
  COUNT(*) AS n
FROM production.public.main_source_wise_leads msw
LEFT JOIN lead_utm lu
  ON lu.phone10 = RIGHT(REGEXP_REPLACE(msw.phone_no1,'[^0-9]',''),10)
  AND lu.wk_mon = DATE_TRUNC('week', msw.created_on_date)::date
WHERE (msw.lead_location = 'BLR_80FT' OR msw.call_location = 'Indiranagar')
  AND msw.created_on_date >= '{start}'
GROUP BY 1,2,3,4
ORDER BY 1 DESC, 5 DESC;
""".format(start=WEEKS[-1])

p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "redshift_query.py")],
                   input=SQL, capture_output=True, text=True)
if p.returncode != 0 or "ERROR" in (p.stderr or ""):
    sys.stderr.write("query failed: " + (p.stderr or "")[:400] + "\n"); sys.exit(1)

BUCKETS = ["gmb_direct", "google_paid", "onsite_web", "walkin", "online_booking", "practo_crm", "outbound_wa", "misattrib", "other"]
# path key -> {bucket, channel, weeks[12]}
paths = {}
buck_tot = {b: [0]*NW for b in BUCKETS}
for line in p.stdout.strip().splitlines():
    c = line.split("\t")
    if len(c) < 5: continue
    mon, bucket, path, channel, n = c[0], c[1], c[2], c[3], c[4]
    if mon not in idx: continue
    i = idx[mon]
    try: n = int(float(n))
    except ValueError: continue
    if bucket in buck_tot: buck_tot[bucket][i] += n
    key = (bucket, path)
    o = paths.setdefault(key, {"bucket": bucket, "path": path, "channel": channel, "weeks": [0]*NW})
    o["weeks"][i] += n

# ---- data_indiranagar_journey.json ----
plist = sorted(paths.values(), key=lambda o: (BUCKETS.index(o["bucket"]) if o["bucket"] in BUCKETS else 9,
                                              -sum(o["weeks"])))
journey = {"_meta": {"clinic": "Bangalore|Indiranagar", "weeks": WEEKS,
                     "source": "production.public.main_source_wise_leads · placed by lead-creation week (created_on_date)",
                     "note": "path = exact entry point (organic_l2) or named paid campaign (google_campaign/fb_campaign). "
                             "WhatsApp/Direct are NOT separately tracked in this table. ~88% of leads book same-day, "
                             "so lead-week ≈ booking-week; the funnel cohort toggle realigns the tail."},
           "paths": plist}
json.dump(journey, open(os.path.join(ROOT, "data_indiranagar_journey.json"), "w"), separators=(",", ":"))

# ---- regenerate data_indiranagar_attribution.json (same numbers, in lockstep) ----
attr = {"_meta": {"clinic": "Bangalore|Indiranagar", "weeks": WEEKS,
                  "source": "production.public.main_source_wise_leads · classified by source × organic_l2 × lead_location",
                  "buckets": "gmb_direct=PC-Inbound+Listing(own GBP) · onsite_web=lead_location BLR_80FT or Clinic Page "
                             "(clinic identified at capture) · walkin · online_booking=lead_location ONLINE (city source, "
                             "clinic set at offline booking) · misattrib=other clinic code · other=rest. "
                             "Regenerated by pull_indiranagar_journey.py — see data_indiranagar_journey.json for exact paths."}}
for b in BUCKETS:
    attr[b] = buck_tot[b]
json.dump(attr, open(os.path.join(ROOT, "data_indiranagar_attribution.json"), "w"), separators=(",", ":"))

print(f"journey paths: {len(plist)} · attribution buckets regenerated")
print("latest-week bucket totals:", {b: buck_tot[b][0] for b in BUCKETS})
print("latest-week top paths:")
for o in sorted(plist, key=lambda o: -o["weeks"][0])[:10]:
    if o["weeks"][0]: print(f"  [{o['bucket']:14}] {o['path']:42} {o['weeks'][0]}")
