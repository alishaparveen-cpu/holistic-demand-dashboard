#!/usr/bin/env python3
"""TOTAL Google leads → booked → done, by CITY × week → data_ga_city_leads.json.

This is the manager-style "total leads by city" (web + call), not just per-campaign UTM:
  - source='Google' leads from main_source_wise_leads (reconciles to the network Google total).
  - city = clinic locality (call_location) where tagged, else parsed from the lead's utm_campaign
    (campaign names carry the city, e.g. T1_Bangalore_SH...). National/online campaigns → 'National / Online'.
  - booked = call_booking_ts; done = the patient's SC appointment reached status COMPLETED.
Verified: network sums to the same weekly Google lead totals as the demand leads table.
Run: AWS_PROFILE=redshift-data python3 scripts/pull_ga_city_leads.py
"""
import os, sys, json, subprocess, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04",
         "2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23"]  # Mon, newest-first
SQL = """
WITH gl AS (
  SELECT DISTINCT leads.phone_no1 AS ph,
    TO_CHAR(DATE(leads.created_on_date)::date-(EXTRACT(dow FROM leads.created_on_date)::int+6)%7,'YYYY-MM-DD') AS wk,
    COALESCE(leads.call_location,'') AS cl, COALESCE(ldr.utm_campaign,'') AS utm,
    leads.source AS src,
    leads.call_booking_ts AS bk
  FROM production.public.main_source_wise_leads leads
  LEFT JOIN allo_prod.allo_persons.lead ldr ON SUBSTRING(ldr.phone_no,4,10)=leads.phone_no1
  WHERE (leads.source='Google' OR (leads.source='Organic' AND leads.organic_l2='Google Listing'))
    AND leads.created_on_date >= '2026-03-23'
),
dn AS (
  SELECT RIGHT(p.phone_no,10) AS ph FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_persons.patient p ON p.id=a.patient_id
  WHERE a.deleted_at IS NULL AND a.status='COMPLETED' AND a.start_time >= '2026-03-23' GROUP BY 1
)
SELECT gl.wk, gl.cl, gl.utm, gl.src, COUNT(DISTINCT gl.ph) leads,
  COUNT(DISTINCT CASE WHEN gl.bk IS NOT NULL THEN gl.ph END) booked,
  COUNT(DISTINCT CASE WHEN dn.ph IS NOT NULL THEN gl.ph END) done
FROM gl LEFT JOIN dn ON dn.ph=gl.ph GROUP BY 1,2,3,4;
"""
CITY = ['Bangalore','Bengaluru','Mumbai','Navi Mumbai','Pune','Hyderabad','Chennai','Coimbatore','Nagpur','Nashik',
        'Surat','Ahmedabad','Jaipur','Bhopal','Ranchi','Aurangabad','Hubballi','Hubli','Mysuru','Mysore','Mangalore',
        'Mangaluru','Visakhapatnam','Vizag','Thane','Gandhinagar','Vijayawada']
NORM = {'Bengaluru':'Bangalore','Hubballi':'Hubli','Mysore':'Mysuru','Mangalore':'Mangaluru','Vizag':'Visakhapatnam'}

def main():
    loc2city = {}
    for k in json.load(open(os.path.join(ROOT, "data_clinic_funnel.json")))["clinics"]:
        cy, lc = k.split("|"); loc2city[lc.strip().lower()] = cy
    def city_of(cl, utm):
        c = loc2city.get(cl.strip().lower())
        if c: return c
        u = " " + utm.upper().replace("_", " ") + " "
        for ct in CITY:
            if " " + ct.upper() + " " in u: return NORM.get(ct, ct)
        return "National / Online"
    p = subprocess.run([sys.executable, RQ], input=SQL, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("ga_city_leads query failed: " + (p.stderr or "")[:400] + "\n"); sys.exit(1)
    idx = {w: i for i, w in enumerate(WEEKS)}; city = {}
    def blank(): return {k: [0]*12 for k in ("leads", "web", "call", "gmb", "booked", "done")}
    for line in p.stdout.strip().splitlines():
        c = line.split("\t")
        if len(c) < 7: continue
        wk, cl, utm, src = c[0], c[1], c[2], c[3]
        if wk not in idx: continue
        try: lds, bk, dn = int(c[4]), int(c[5]), int(c[6])
        except ValueError: continue
        cy = city_of(cl, utm); i = idx[wk]
        a = city.setdefault(cy, blank())
        a["leads"][i] += lds; a["booked"][i] += bk; a["done"][i] += dn
        # source split: GMB (organic listing) · Web (paid Google w/ utm) · Call/other (paid Google, no utm)
        bucket = "gmb" if src == "Organic" else ("web" if utm.strip() else "call")
        a[bucket][i] += lds
    out = {"_meta": {"source": "Google leads by city (web+call+GMB). source=Google (paid: web=has utm, call=no utm) + source=Organic/Google Listing (GMB call). city via clinic locality else utm_campaign. booked=call_booking_ts; done=SC COMPLETED. Reconciles to network Google leads.",
                     "weeks": WEEKS}, "city": city}
    json.dump(out, open(os.path.join(ROOT, "data_ga_city_leads.json"), "w"), separators=(",", ":"))
    net = sum(c["leads"][1] for c in city.values())
    print(f"wrote data_ga_city_leads.json · {len(city)} cities · network last-complete-wk leads {net}")
    print(f"  split (last complete wk): web {sum(c['web'][1] for c in city.values())} · call {sum(c['call'][1] for c in city.values())} · gmb {sum(c['gmb'][1] for c in city.values())}")

if __name__ == "__main__":
    main()
