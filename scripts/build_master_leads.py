#!/usr/bin/env python3
"""Fresh-new-leads layer for the master sheet — network level, by source, by week.

A 'new lead' = a phone's FIRST-EVER lead (main_source_wise_leads), bucketed by that first
week. For each (week, source): new_leads, booked_same_week, booked_later, never_booked.
booked_same_week ties to the funnel's new-this-week bookings; never_booked = demand that
never converted. NO clinic/city split — unbooked leads carry no location, so leads are a
national / by-source layer only (that's a data limitation, not a choice).

Writes _meta.master_leads into data_source_recon.json (same newest-first week order).
Run: AWS_PROFILE=redshift-data python3 scripts/build_master_leads.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import patch_subcat as PS
ROOT = PS.ROOT; OUT = os.path.join(ROOT, "data_source_recon.json")
idx = PS.idx; Z = PS.Z; LO = PS.LO; run_sql = PS.run_sql
# channel taxonomy aligned with bookings (source + organic_l2), so leads split into GMB / Google / Meta / Call-in / etc.
SRCS = ["GMB", "Google Ads", "Meta", "WhatsApp", "Walk-in", "Website", "Practo", "JustDial", "Organic (untagged)", "Other"]

SQL = """WITH ld AS (
  SELECT phone_no1 ph, source, organic_l2, created_on_date::date d,
    ROW_NUMBER() OVER (PARTITION BY phone_no1 ORDER BY created_on_date) rn
  FROM production.public.main_source_wise_leads WHERE created_on_date >= '2023-01-01'),
 fl AS (SELECT ph, source, organic_l2, DATE_TRUNC('week', d + INTERVAL '5 hours 30 minutes')::date fwk FROM ld WHERE rn=1),
 fb AS (SELECT phone_no1 ph, MIN(call_booking_ts) fbt FROM production.public.main_source_wise_leads
        WHERE call_booking_ts IS NOT NULL GROUP BY 1)
SELECT TO_CHAR(fl.fwk,'YYYY-MM-DD') wk,
  CASE WHEN fl.source='Google' THEN 'Google Ads'
       WHEN fl.source IN ('Fb','Facebook','Instagram','Ig','Meta') THEN 'Meta'
       WHEN fl.source='Organic' AND fl.organic_l2 IN ('Google Listing','PC-Inbound') THEN 'GMB'
       WHEN fl.source='Organic' AND fl.organic_l2='WA-Inbound' THEN 'WhatsApp'
       WHEN fl.source='Organic' AND fl.organic_l2='Walk In' THEN 'Walk-in'
       WHEN fl.source='Organic' AND fl.organic_l2 IN ('Clinic Page','Doctor','Doctor Pages','Sexologist','Treatment Page','Login Page','Healthfeed','Webbot','Homepage','Blog','STD Testing','Assessment Page') THEN 'Website'
       WHEN fl.source='Organic' THEN 'Organic (untagged)'
       WHEN fl.source='Justdial' THEN 'JustDial'
       WHEN fl.source ILIKE 'Practo%' THEN 'Practo'
       ELSE 'Other' END src,
  COUNT(*) new_leads,
  SUM(CASE WHEN fb.fbt IS NOT NULL AND DATE_TRUNC('week',fb.fbt+INTERVAL '5 hours 30 minutes')::date=fl.fwk THEN 1 ELSE 0 END) booked_same,
  SUM(CASE WHEN fb.fbt IS NOT NULL AND DATE_TRUNC('week',fb.fbt+INTERVAL '5 hours 30 minutes')::date>fl.fwk THEN 1 ELSE 0 END) booked_later,
  SUM(CASE WHEN fb.fbt IS NULL THEN 1 ELSE 0 END) never_booked
FROM fl LEFT JOIN fb ON fb.ph=fl.ph
WHERE fl.fwk >= '{lo}' AND fl.fwk < '2026-06-29'
GROUP BY 1,2;""".format(lo=LO)

# Practo leads are NOT in main_source_wise_leads — they live in allo_persons.lead (utm_source='practo').
# Same first-ever-phone-by-week logic; booked timing from bookings_data_raw (apt_create_dt).
PRACTO_SQL = """WITH pl AS (
  SELECT RIGHT(phone_no,10) ph,
    DATE_TRUNC('week', created_at + INTERVAL '5 hours 30 minutes')::date wk,
    ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY created_at) rn
  FROM allo_prod.allo_persons.lead
  WHERE utm_source ILIKE 'practo' AND created_at >= '2023-01-01' AND phone_no IS NOT NULL),
 fl AS (SELECT ph, wk FROM pl WHERE rn=1),
 fb AS (SELECT phone_no ph10, MIN(DATE_TRUNC('week', apt_create_dt + INTERVAL '5 hours 30 minutes')::date) fbw
        FROM production.public.bookings_data_raw GROUP BY 1)
SELECT TO_CHAR(fl.wk,'YYYY-MM-DD') wk, COUNT(*) new_leads,
  SUM(CASE WHEN fb.fbw = fl.wk THEN 1 ELSE 0 END) booked_same,
  SUM(CASE WHEN fb.fbw > fl.wk THEN 1 ELSE 0 END) booked_later,
  SUM(CASE WHEN fb.fbw IS NULL OR fb.fbw < fl.wk THEN 1 ELSE 0 END) never_booked
FROM fl LEFT JOIN fb ON RIGHT(fb.ph10,10)=fl.ph
WHERE fl.wk >= '{lo}' AND fl.wk < '2026-06-29'
GROUP BY 1;""".format(lo=LO)

FIELDS = ["new_leads", "booked_same", "booked_later", "never_booked"]
if __name__ == "__main__":
    d = json.load(open(OUT))
    by_src = {s: {f: Z() for f in FIELDS} for s in SRCS}
    for line in run_sql(SQL):
        r = line.split("\t") if isinstance(line, str) else line
        if len(r) < 6: continue
        wk, src, nl, bs, bl, nb = r[:6]
        if wk not in idx: continue
        if src not in SRCS: src = "Other"
        i = idx[wk]
        try:
            by_src[src]["new_leads"][i] += int(float(nl)); by_src[src]["booked_same"][i] += int(float(bs))
            by_src[src]["booked_later"][i] += int(float(bl)); by_src[src]["never_booked"][i] += int(float(nb))
        except (ValueError, TypeError): continue
    # Practo leads from the DATABASE (allo_persons.lead utm_source='practo') — not in main_source_wise_leads.
    for line in run_sql(PRACTO_SQL):
        r = line.split("\t") if isinstance(line, str) else line
        if len(r) < 5: continue
        wk, nl, bs, bl, nb = r[:5]
        if wk not in idx: continue
        i = idx[wk]
        try:
            by_src["Practo"]["new_leads"][i] += int(float(nl)); by_src["Practo"]["booked_same"][i] += int(float(bs))
            by_src["Practo"]["booked_later"][i] += int(float(bl)); by_src["Practo"]["never_booked"][i] += int(float(nb))
        except (ValueError, TypeError): continue
    total = {f: [sum(by_src[s][f][i] for s in SRCS) for i in range(len(Z()))] for f in FIELDS}
    d["_meta"]["master_leads"] = {"sources": SRCS, "by_source": by_src, "total": total,
        "note": "new lead = phone's first-ever lead, by first week; booked_same ties to new-this-week bookings; no geo split (unbooked leads have no clinic)"}
    json.dump(d, open(OUT, "w"), separators=(",", ":"))
    tn = sum(total["new_leads"]); tb = sum(total["booked_same"]) + sum(total["booked_later"]); tnv = sum(total["never_booked"])
    print("new leads %d | booked eventually %d (%.0f%%) | never %d" % (tn, tb, 100 * tb / tn if tn else 0, tnv))
    print("by source (new leads):", {s: sum(by_src[s]["new_leads"]) for s in SRCS})
