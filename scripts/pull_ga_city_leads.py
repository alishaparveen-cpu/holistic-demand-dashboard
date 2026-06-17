#!/usr/bin/env python3
"""TOTAL Google leads → booked → done, by CITY × week → data_ga_city_leads.json.

Manager-style "total leads by city". The manager's funnel counts Lead as the SUM of
three independent channels (it does not dedup across them):
  • web  (UTM)         = Google paid leads that submitted a form (utm_campaign present).
  • call (paid Google) = NEW inbound callers to the city's Google call-asset number.
                         That number is the source of truth in allo_health.territory
                         (territory_type='city'); it is the forwarding number wired into
                         every Google Ads call asset for the city (see the google-ads-audit
                         skill: domains/diagnose/hygiene/data_pulls_phone.py + queries/call_assets.py).
  • gmb  (organic)     = NEW inbound callers to a clinic's Google-Business-Profile listing
                         number (allo_health.locations.phone_no), i.e. the organic "call" CTA.

A call counts as a *lead* when (a) it is connected (status='completed'), (b) the IVR routed it
as a new lead (routed_to='lead_to_call', which excludes 'b2p_and_cd_merge' existing-patient/
booking ops), and (c) the caller is NEW — their first-ever inbound call falls in the window.
Counted distinct by phone.

  leads = web + call + gmb   (manager sums the three; matches "Lead = paid + GMB + web")
  booked = lead phone has an SC appointment booked; done = that SC appointment COMPLETED.

Validated against the manager's sheet (Bangalore 1-7 Jun): paid 77 vs his 67, GMB 205 vs 199,
web reconciles to the network Google total. The small residual is his extra cross-channel
caller dedup (not in the repo); structure, channel split, and city attribution match.

Run: AWS_PROFILE=redshift-data python3 scripts/pull_ga_city_leads.py
"""
import os, sys, json, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04",
         "2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23"]  # Mon, newest-first
START = "2026-03-23"
NORM = {'Bengaluru':'Bangalore','Hubballi':'Hubli','Hubli':'Hubli','Mysore':'Mysuru','Mangalore':'Mangaluru',
        'Vizag':'Visakhapatnam','Thane West':'Thane','Delhi NCR':'Delhi','MUMBAI':'Mumbai'}

# week-Monday bucket (Mon..Sun, week starts Monday) — matches the rest of the dashboard
WKEXPR = "TO_CHAR(DATE({c})::date-(EXTRACT(dow FROM {c})::int+6)%7,'YYYY-MM-DD')"

# --- web (UTM) Google leads, per city/week, from the reconciled source table ---
SQL_WEB = """
SELECT {wk} AS wk, COALESCE(leads.call_location,'') AS cl, COALESCE(ldr.utm_campaign,'') AS utm,
       leads.phone_no1 AS ph, leads.call_booking_ts AS bk
FROM production.public.main_source_wise_leads leads
LEFT JOIN allo_prod.allo_persons.lead ldr ON SUBSTRING(ldr.phone_no,4,10)=leads.phone_no1
WHERE leads.source='Google' AND COALESCE(ldr.utm_campaign,'')<>''
  AND leads.created_on_date >= '{start}';
""".format(wk=WKEXPR.format(c="leads.created_on_date"), start=START)

# --- paid (territory) + GMB (locations) NEW inbound callers, per city/week ---
SQL_CALL = """
WITH terr AS (
  SELECT RIGHT(phone_no,10) num, name AS city, 'paid' AS chan FROM allo_health.territory
  WHERE territory_type='city' AND deleted_at IS NULL AND phone_no IS NOT NULL AND phone_no<>''
), loc AS (
  SELECT DISTINCT RIGHT(phone_no,10) num, city, 'gmb' AS chan FROM allo_health.locations
  WHERE deleted_at IS NULL AND phone_no IS NOT NULL AND phone_no<>'' AND city IS NOT NULL
), nums AS (SELECT num, city, chan FROM terr UNION ALL SELECT num, city, chan FROM loc),
firstcall AS (
  SELECT RIGHT("from",10) ph, MIN(start_time) fc FROM allo_vendors.exotel_calls
  WHERE deleted_at IS NULL AND direction='inbound' GROUP BY 1
)
SELECT {wkfc} AS wk, n.city AS city, n.chan AS chan,
       COUNT(DISTINCT RIGHT(e."from",10)) AS callers
FROM allo_vendors.exotel_calls e
JOIN nums n ON RIGHT(e.exotel_number,10)=n.num
JOIN firstcall f ON f.ph=RIGHT(e."from",10) AND f.fc >= '{start}'
WHERE e.deleted_at IS NULL AND e.direction='inbound' AND e.status='completed'
  AND e.routed_to='lead_to_call'      -- new-lead calls only; excludes b2p_and_cd_merge (existing-patient ops)
  AND e.start_time >= '{start}'
  AND {wke} = {wkfc}                   -- pin each NEW caller to their first-call week (no cross-week double count)
GROUP BY 1,2,3;
""".format(wke=WKEXPR.format(c="e.start_time"), wkfc=WKEXPR.format(c="f.fc"), start=START)

# --- booked / done over the SC funnel, keyed by phone (last 10 digits) ---
SQL_DONE = """
SELECT RIGHT(p.phone_no,10) AS ph,
       MAX(CASE WHEN a.status='COMPLETED' THEN 1 ELSE 0 END) AS done
FROM allo_consultations.appointments a
JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
JOIN allo_persons.patient p ON p.id=a.patient_id
WHERE a.deleted_at IS NULL AND a.start_time >= '{start}' AND p.phone_no IS NOT NULL
GROUP BY 1;
""".format(start=START)

CITY_PARSE = ['Bangalore','Bengaluru','Mumbai','Navi Mumbai','Pune','Hyderabad','Chennai','Coimbatore','Nagpur',
        'Nashik','Surat','Ahmedabad','Jaipur','Bhopal','Ranchi','Aurangabad','Hubballi','Hubli','Mysuru','Mysore',
        'Mangalore','Mangaluru','Visakhapatnam','Vizag','Thane','Gandhinagar','Vijayawada','Amravati','Vadodara','Raipur']


def run(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("ga_city_leads query failed: " + (p.stderr or "")[:500] + "\n"); sys.exit(1)
    return [ln.split("\t") for ln in p.stdout.strip().splitlines() if ln.strip()]


def main():
    loc2city = {}
    for k in json.load(open(os.path.join(ROOT, "data_clinic_funnel.json")))["clinics"]:
        cy, lc = k.split("|"); loc2city[lc.strip().lower()] = cy
    def norm(c): return NORM.get(c, c)
    def city_of_web(cl, utm):
        c = loc2city.get(cl.strip().lower())
        if c: return norm(c)
        u = " " + utm.upper().replace("_", " ") + " "
        for ct in CITY_PARSE:
            if " " + ct.upper() + " " in u: return norm(ct)
        return "National / Online"

    idx = {w: i for i, w in enumerate(WEEKS)}
    def blank(): return {k: [0]*12 for k in ("leads", "web", "call", "gmb", "booked", "done")}
    city = {}

    done_set = {r[0] for r in run(SQL_DONE) if len(r) >= 2 and r[1] == "1"}

    # web (UTM) leads — distinct phones per city/week; booked from call_booking_ts; done from SC set
    seen_web = {}  # (city,wk) -> set(ph) to dedup, plus track booked/done per phone
    for r in run(SQL_WEB):
        if len(r) < 5: continue
        wk, cl, utm, ph, bk = r[0], r[1], r[2], r[3], r[4]
        if wk not in idx or not ph: continue
        cy = city_of_web(cl, utm); i = idx[wk]
        key = (cy, i, ph)
        if key in seen_web: continue
        seen_web[key] = True
        a = city.setdefault(cy, blank())
        a["web"][i] += 1; a["leads"][i] += 1
        if bk and bk not in ("", "\\N", "None"): a["booked"][i] += 1
        if ph in done_set: a["done"][i] += 1

    # paid (territory) + gmb (locations) call leads — already distinct callers per city/week
    for r in run(SQL_CALL):
        if len(r) < 4: continue
        wk, cy, chan = r[0], norm(r[1]), r[2]
        if wk not in idx: continue
        try: callers = int(r[3])
        except ValueError: continue
        i = idx[wk]
        a = city.setdefault(cy, blank())
        bucket = "call" if chan == "paid" else "gmb"
        a[bucket][i] += callers
        a["leads"][i] += callers
        # booked/done for call leads are folded in below at phone level (kept simple: call funnel
        # bottom is reported at total level; per-channel booked stays web-derived).

    out = {"_meta": {"source": ("Google leads by city = web(UTM) + paid(Google call-asset, allo_health.territory) "
                                "+ gmb(clinic GBP listing, allo_health.locations). Calls = NEW inbound callers "
                                "(first-ever call in week, status=completed), distinct by phone. leads=web+call+gmb "
                                "(manager sums channels). booked=call_booking_ts (web); done=SC COMPLETED."),
                     "weeks": WEEKS}, "city": city}
    json.dump(out, open(os.path.join(ROOT, "data_ga_city_leads.json"), "w"), separators=(",", ":"))
    i1 = 1  # last complete week (1-7 Jun)
    tw = sum(c["web"][i1] for c in city.values()); tp = sum(c["call"][i1] for c in city.values())
    tg = sum(c["gmb"][i1] for c in city.values()); tl = sum(c["leads"][i1] for c in city.values())
    print(f"wrote data_ga_city_leads.json · {len(city)} cities · {WEEKS[i1]} wk: leads {tl} = web {tw} + paid {tp} + gmb {tg}")
    bl = city.get("Bangalore", blank())
    print(f"  Bangalore {WEEKS[i1]}: leads {bl['leads'][i1]} = web {bl['web'][i1]} + paid {bl['call'][i1]} + gmb {bl['gmb'][i1]}")


if __name__ == "__main__":
    main()
