#!/usr/bin/env python3
"""L2B (lead-to-book) demand funnel — weekly, reconciled across two systems.

Base spine = exotel_calls (colleague's L2C definition: inbound + routed_to='lead_to_call',
Practo line excluded, one row per patient per week). We bolt on OUR booking (appointments)
and OUR source (main_source_wise_leads UTM), so the funnel ties to the leads data on phone.

Emits data_l2b.json:
  weeks:  ["2026-06-01", ...] newest-last
  leads:  {week: {new_leads, called}}                  # this-week new leads & how many called
  caller: {week: [{vintage,tier,channel,callers,booked}, ...]}  # granular cube of the callers
Source priority per caller: UTM tag (lead pre-existed call) -> dialed number -> undetermined.
Run: AWS_PROFILE=redshift-data python3 scripts/build_l2b.py
"""
import os, sys, json, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ   = os.path.join(ROOT, "scripts", "redshift_query.py")
OUT  = os.path.join(ROOT, "data_l2b.json")
FLOOR = "2026-05-01"   # weeks from here forward appear in the panel

CALLER_SQL = """
WITH terr AS (SELECT DISTINCT phone_no FROM allo_prod.allo_health.territory WHERE territory_type='city' AND is_active=true),
 loc AS (SELECT DISTINCT phone_no FROM allo_prod.allo_health.locations WHERE type='offline' AND is_active=true AND deleted_at IS NULL),
 caller AS (SELECT pid, call_wk, ph10, chan FROM (
    SELECT ec.user_id pid, DATE_TRUNC('week',DATEADD(minute,330,ec.created_at))::date call_wk, RIGHT(p.phone_no,10) ph10,
      CASE WHEN t.phone_no IS NOT NULL THEN 'Google Ads' WHEN l.phone_no IS NOT NULL THEN 'GMB' ELSE 'Other' END chan,
      ROW_NUMBER() OVER (PARTITION BY ec.user_id, DATE_TRUNC('week',DATEADD(minute,330,ec.created_at)) ORDER BY ec.created_at) rn
    FROM allo_prod.allo_vendors.exotel_calls ec JOIN allo_prod.allo_persons.patient p ON p.id=ec.user_id
    LEFT JOIN terr t ON t.phone_no=CASE WHEN LEFT(ec.exotel_number,1)='0' THEN '+91'||SUBSTRING(ec.exotel_number,2) ELSE ec.exotel_number END
    LEFT JOIN loc  l ON l.phone_no=CASE WHEN LEFT(ec.exotel_number,1)='0' THEN '+91'||SUBSTRING(ec.exotel_number,2) ELSE ec.exotel_number END
    WHERE ec.direction IN ('inbound','incoming') AND ec.routed_to='lead_to_call' AND ec.exotel_number!='08071176846'
      AND ec.user_id IS NOT NULL AND DATE_TRUNC('week',DATEADD(minute,330,ec.created_at))::date>='{floor}') WHERE rn=1),
 fl AS (SELECT RIGHT(phone_no1,10) ph10, DATE_TRUNC('week',MIN(created_on_date))::date flw FROM production.public.main_source_wise_leads GROUP BY 1),
 rt AS (SELECT ph10, acqtag FROM (SELECT RIGHT(phone_no1,10) ph10,
      CASE WHEN source='Google' THEN 'Google Ads' WHEN source IN ('Fb','Facebook','Instagram','Meta') THEN 'Meta'
           WHEN source='Organic' AND organic_l2='Google Listing' THEN 'GMB'
           WHEN source='Organic' AND organic_l2 IN ('Clinic Page','Doctor','Sexologist','Treatment Page','Login Page','Assessment Page','ED Page','PE Page','Homepage','Home Page','Blog','Webbot','Healthfeed') THEN 'Organic/Web'
           WHEN source ILIKE 'Practo%' THEN 'Practo' WHEN source='Newspaper' THEN 'Newspaper' WHEN source='Youtube' THEN 'YouTube' ELSE NULL END acqtag,
      ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no1,10) ORDER BY (CASE WHEN source IN ('Google','Fb','Facebook','Instagram','Meta','Newspaper','Youtube') OR source ILIKE 'Practo%'
             OR (source='Organic' AND organic_l2 IN ('Google Listing','Clinic Page','Doctor','Sexologist','Treatment Page','Login Page','Assessment Page','ED Page','PE Page','Homepage','Home Page','Blog','Webbot','Healthfeed')) THEN 0 ELSE 1 END), created_on_date) rn
    FROM production.public.main_source_wise_leads) WHERE rn=1),
 bka AS (SELECT patient_id pid, DATE_TRUNC('week',DATEADD(minute,330,MIN(created_at)))::date bwk FROM allo_prod.allo_consultations.appointments WHERE deleted_at IS NULL GROUP BY 1)
SELECT TO_CHAR(c.call_wk,'YYYY-MM-DD') week,
  CASE WHEN fl.flw IS NULL THEN 'no_lead' WHEN fl.flw=c.call_wk THEN 'this_wk' WHEN fl.flw<c.call_wk THEN 'earlier' ELSE 'after' END vintage,
  CASE WHEN rt.acqtag IS NOT NULL THEN 'tag' WHEN c.chan IN ('Google Ads','GMB') THEN 'dialed' ELSE 'undet' END tier,
  CASE WHEN rt.acqtag IS NOT NULL THEN rt.acqtag WHEN c.chan IN ('Google Ads','GMB') THEN c.chan ELSE 'Undetermined' END channel,
  COUNT(*) callers,
  SUM(CASE WHEN b.bwk=c.call_wk THEN 1 ELSE 0 END) booked
FROM caller c LEFT JOIN fl ON fl.ph10=c.ph10 LEFT JOIN rt ON rt.ph10=c.ph10 LEFT JOIN bka b ON b.pid=c.pid
GROUP BY 1,2,3,4;
""".replace("{floor}", FLOOR)

LEADS_SQL = """
WITH lead1 AS (SELECT RIGHT(phone_no1,10) ph10, DATE_TRUNC('week',MIN(created_on_date))::date flw FROM production.public.main_source_wise_leads GROUP BY 1),
 callwk AS (SELECT DISTINCT RIGHT(p.phone_no,10) ph10, DATE_TRUNC('week',DATEADD(minute,330,ec.created_at))::date cwk
  FROM allo_prod.allo_vendors.exotel_calls ec JOIN allo_prod.allo_persons.patient p ON p.id=ec.user_id
  WHERE ec.direction IN ('inbound','incoming') AND ec.routed_to='lead_to_call' AND ec.exotel_number!='08071176846' AND ec.user_id IS NOT NULL)
SELECT TO_CHAR(l.flw,'YYYY-MM-DD') week, COUNT(DISTINCT l.ph10) new_leads,
  COUNT(DISTINCT CASE WHEN cw.cwk=l.flw THEN l.ph10 END) called_n
FROM lead1 l LEFT JOIN callwk cw ON cw.ph10=l.ph10
WHERE l.flw>='{floor}' GROUP BY 1;
""".replace("{floor}", FLOOR)


def run(sql):
    env = {**os.environ, "AWS_PROFILE": "redshift-data"}
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True, env=env)
    out = (p.stdout or "").strip()
    if p.returncode != 0 or out.startswith("FAIL") or "Traceback" in (p.stderr or ""):
        sys.exit("query failed:\n" + (p.stderr or out)[-800:])
    rows = []
    for line in out.split("\n"):
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("FAIL"):
            continue
        rows.append(line.split("\t"))
    return rows


if __name__ == "__main__":
    caller = {}
    for r in run(CALLER_SQL):
        if len(r) < 6:
            continue
        wk, vintage, tier, channel, callers, booked = r[:6]
        caller.setdefault(wk, []).append({
            "vintage": vintage, "tier": tier, "channel": channel,
            "callers": int(float(callers)), "booked": int(float(booked))})
    leads = {}
    for r in run(LEADS_SQL):
        if len(r) < 3:
            continue
        wk, nl, cl = r[:3]
        leads[wk] = {"new_leads": int(float(nl)), "called": int(float(cl))}
    weeks = sorted(set(list(caller.keys()) + list(leads.keys())))
    json.dump({"weeks": weeks, "leads": leads, "caller": caller},
              open(OUT, "w"), separators=(",", ":"))
    # console reconciliation for the newest complete-ish week
    for wk in weeks[-3:]:
        rows = caller.get(wk, [])
        tc = sum(x["callers"] for x in rows); tb = sum(x["booked"] for x in rows)
        print("%s : callers %d  booked %d  L2B %.1f%%  | new_leads %d called %d" % (
            wk, tc, tb, (100.0 * tb / tc if tc else 0),
            leads.get(wk, {}).get("new_leads", 0), leads.get(wk, {}).get("called", 0)))
    print("wrote", OUT)
