#!/usr/bin/env python3
"""Organic sub-channel weekly breakdown → data_organic_sub.json, replicating how the L0 sheet
splits organic: main_source_wise_leads JOIN allo_persons.lead, classified on utm_medium /
organic_l2 / user_flow (NOT organic_l2 alone — WhatsApp lives in lead.utm_medium).

Buckets: WhatsApp · PC-Inbound (calls) · GMB/Listing · High-intent (assessment) · Other.
Weekly (Mon), newest-first, aligned to the efficiency 12-week window. leads + booked per bucket.
Run: AWS_PROFILE=redshift-data python3 scripts/pull_organic_sub.py
"""
import os, sys, json, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11",
         "2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]  # Mon, newest-first
BUCKETS = ["WhatsApp","PC-Inbound","GMB/Listing","High-intent","Other"]

SQL = """
SELECT TO_CHAR(DATE(leads.created_on_date)::date - (EXTRACT(dow FROM leads.created_on_date)::int + 6) % 7, 'YYYY-MM-DD') AS wk_mon,
  CASE
    WHEN LOWER(COALESCE(ldr.utm_medium,'')) = 'whatsapp' THEN 'WhatsApp'
    WHEN leads.organic_l2 = 'PC-Inbound' OR ldr.utm_medium ~ '^[0-9]{8,}$' THEN 'PC-Inbound'
    WHEN leads.organic_l2 = 'Google Listing' OR LOWER(COALESCE(ldr.utm_medium,'')) IN ('listing','clinic-listing','clinic') THEN 'GMB/Listing'
    WHEN LOWER(COALESCE(ldr.user_flow,'')) LIKE '%assessment%' OR LOWER(COALESCE(ldr.source_url,'')) LIKE '%assessment%' OR LOWER(COALESCE(ldr.source_url,'')) LIKE '%quiz%' THEN 'High-intent'
    ELSE 'Other' END AS bucket,
  COUNT(*) AS leads, COUNT(leads.call_booking_ts) AS booked
FROM production.public.main_source_wise_leads leads
LEFT JOIN allo_prod.allo_persons.lead ldr ON SUBSTRING(ldr.phone_no,4,10) = leads.phone_no1
WHERE leads.source='Organic' AND leads.created_on_date >= '2026-03-30'
GROUP BY 1,2 ORDER BY 1,2;
"""

def main():
    p = subprocess.run([sys.executable, RQ], input=SQL, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("organic-sub query failed: " + (p.stderr or "")[:400] + "\n"); sys.exit(1)
    idx = {w: i for i, w in enumerate(WEEKS)}
    data = {b: {"leads": [0]*len(WEEKS), "booked": [0]*len(WEEKS)} for b in BUCKETS}
    for line in p.stdout.strip().splitlines():
        c = line.split("\t")
        if len(c) < 4: continue
        wk, bucket, leads, booked = c[0], c[1], c[2], c[3]
        if wk not in idx or bucket not in data: continue
        data[bucket]["leads"][idx[wk]] = int(float(leads or 0))
        data[bucket]["booked"][idx[wk]] = int(float(booked or 0))
    out = {"_meta": {"source": "main_source_wise_leads JOIN allo_persons.lead, classified on utm_medium/organic_l2/user_flow (replicates L0 sheet organic split)",
                     "weeks": WEEKS, "buckets": BUCKETS}, "buckets": data}
    json.dump(out, open(os.path.join(ROOT, "data_organic_sub.json"), "w"), separators=(",", ":"))
    print("wrote data_organic_sub.json")
    for b in BUCKETS:
        print(f"  {b:14} leads(newest→) {data[b]['leads']}  · booked wk0 {data[b]['booked'][0]}")

if __name__ == "__main__":
    main()
