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
SRCS = ["Google", "Meta", "Organic", "Practo", "GMB", "Other"]

SQL = """WITH ld AS (
  SELECT phone_no1 ph, source, created_on_date::date d,
    ROW_NUMBER() OVER (PARTITION BY phone_no1 ORDER BY created_on_date) rn
  FROM production.public.main_source_wise_leads WHERE created_on_date >= '2023-01-01'),
 fl AS (SELECT ph, source, DATE_TRUNC('week', d + INTERVAL '5 hours 30 minutes')::date fwk FROM ld WHERE rn=1),
 fb AS (SELECT phone_no1 ph, MIN(call_booking_ts) fbt FROM production.public.main_source_wise_leads
        WHERE call_booking_ts IS NOT NULL GROUP BY 1)
SELECT TO_CHAR(fl.fwk,'YYYY-MM-DD') wk,
  CASE WHEN fl.source='Google' THEN 'Google'
       WHEN fl.source IN ('Fb','Facebook','Instagram','Ig','Meta') THEN 'Meta'
       WHEN fl.source='Organic' THEN 'Organic'
       WHEN fl.source ILIKE 'Practo%' THEN 'Practo'
       WHEN fl.source ILIKE 'GMB%' OR fl.source='Google Listing' THEN 'GMB'
       ELSE 'Other' END src,
  COUNT(*) new_leads,
  SUM(CASE WHEN fb.fbt IS NOT NULL AND DATE_TRUNC('week',fb.fbt+INTERVAL '5 hours 30 minutes')::date=fl.fwk THEN 1 ELSE 0 END) booked_same,
  SUM(CASE WHEN fb.fbt IS NOT NULL AND DATE_TRUNC('week',fb.fbt+INTERVAL '5 hours 30 minutes')::date>fl.fwk THEN 1 ELSE 0 END) booked_later,
  SUM(CASE WHEN fb.fbt IS NULL THEN 1 ELSE 0 END) never_booked
FROM fl LEFT JOIN fb ON fb.ph=fl.ph
WHERE fl.fwk >= '{lo}' AND fl.fwk < '2026-06-29'
GROUP BY 1,2;""".format(lo=LO)

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
    # fold in Practo — not in main_source_wise_leads; comes from the Practo marketplace sheet
    # (per-clinic, clinic-attributed, recent ~12 weeks only). new_leads=leads, booked_same≈booked.
    try:
        pc = json.load(open(os.path.join(ROOT, "data_practo_conv.json")))
        pw = pc["_meta"]["weeks"]
        for k, v in pc.items():
            if k == "_meta": continue
            for wi, wk in enumerate(pw):
                if wk not in idx: continue
                i = idx[wk]
                ld = (v.get("leads") or [0] * len(pw))[wi] if wi < len(v.get("leads", [])) else 0
                bk = (v.get("booked") or [0] * len(pw))[wi] if wi < len(v.get("booked", [])) else 0
                by_src["Practo"]["new_leads"][i] += ld
                by_src["Practo"]["booked_same"][i] += bk
                by_src["Practo"]["never_booked"][i] += max(0, ld - bk)
    except Exception as e:
        print("practo fold skipped:", e)
    total = {f: [sum(by_src[s][f][i] for s in SRCS) for i in range(len(Z()))] for f in FIELDS}
    d["_meta"]["master_leads"] = {"sources": SRCS, "by_source": by_src, "total": total,
        "note": "new lead = phone's first-ever lead, by first week; booked_same ties to new-this-week bookings; no geo split (unbooked leads have no clinic)"}
    json.dump(d, open(OUT, "w"), separators=(",", ":"))
    tn = sum(total["new_leads"]); tb = sum(total["booked_same"]) + sum(total["booked_later"]); tnv = sum(total["never_booked"])
    print("new leads %d | booked eventually %d (%.0f%%) | never %d" % (tn, tb, 100 * tb / tn if tn else 0, tnv))
    print("by source (new leads):", {s: sum(by_src[s]["new_leads"]) for s in SRCS})
