#!/usr/bin/env python3
"""Resolved L2B funnel — corrected attribution, DAY-of-week granular (for week-to-date compare).

Source per caller: exotel number dialed -> number_source_overrides.csv (audited) -> CRM utm_source
-> Undetermined. Provenance: system / corrected / confirmed / unclassified. Vintage: this_wk /
earlier / no_lead (lead-after-call folded into this_wk).

Every metric is stored as two 7-slot arrays indexed by day-of-week (0=Mon..6=Sun):
  cal[d] = callers whose FIRST call was on day d ; bkd[d] = callers who BOOKED (same wk) on day d.
The page sums days 0..N for a Mon–dayN window (full week = N=6), so partial weeks compare like-for-like.

Emits data_l2b_final.json:
  weeks, chan{wk:{ch:{cal[7],bkd[7]}}}, prov{...}, vint{...}, leadsnew{wk:[7]}  (new leads by create-day)
Run: AWS_PROFILE=redshift-data python3 scripts/build_l2b_final.py
"""
import os, sys, json, csv, subprocess
from collections import defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ   = os.path.join(ROOT, "scripts", "redshift_query.py")
OVR  = os.path.join(ROOT, "number_source_overrides.csv")
OUT  = os.path.join(ROOT, "data_l2b_final.json")
FLOOR = "2026-04-13"   # ~12 complete weeks of history for the up-to-10-week toggle

RES_SQL = """
WITH caller AS (SELECT pid, call_wk, ph10, exonum, fcts FROM (
    SELECT ec.user_id pid, DATE_TRUNC('week',DATEADD(minute,330,ec.created_at))::date call_wk,
      RIGHT(p.phone_no,10) ph10, ec.exotel_number exonum, DATEADD(minute,330,ec.created_at) fcts,
      ROW_NUMBER() OVER (PARTITION BY ec.user_id, DATE_TRUNC('week',DATEADD(minute,330,ec.created_at)) ORDER BY ec.created_at) rn
    FROM allo_prod.allo_vendors.exotel_calls ec JOIN allo_prod.allo_persons.patient p ON p.id=ec.user_id
    WHERE ec.direction IN ('inbound','incoming') AND ec.routed_to='lead_to_call' AND ec.exotel_number!='08071176846'
      AND ec.user_id IS NOT NULL AND DATE_TRUNC('week',DATEADD(minute,330,ec.created_at))::date>='{floor}') WHERE rn=1),
 crm AS (SELECT ph10, us FROM (SELECT RIGHT(phone_no,10) ph10, LOWER(CAST(utm_source AS VARCHAR)) us,
          ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY updated_at DESC NULLS LAST) rn
        FROM allo_prod.allo_persons.lead WHERE phone_no IS NOT NULL) WHERE rn=1),
 bka AS (SELECT patient_id pid, MIN(DATEADD(minute,330,created_at)) bts FROM allo_prod.allo_consultations.appointments WHERE deleted_at IS NULL GROUP BY 1),
 fl AS (SELECT RIGHT(phone_no1,10) ph10, DATE_TRUNC('week',MIN(created_on_date))::date flw FROM production.public.main_source_wise_leads GROUP BY 1)
SELECT TO_CHAR(c.call_wk,'YYYY-MM-DD') week, c.exonum,
  CASE WHEN crm.us IS NULL OR crm.us IN ('','null') THEN '(none)' ELSE crm.us END crm_source,
  CASE WHEN fl.flw IS NULL THEN 'no_lead' WHEN fl.flw<c.call_wk THEN 'earlier' ELSE 'this_wk' END vintage,
  DATEDIFF(day, c.call_wk, c.fcts::date) call_day,
  CASE WHEN b.bts IS NOT NULL AND DATE_TRUNC('week',b.bts)::date=c.call_wk THEN DATEDIFF(day, c.call_wk, b.bts::date) ELSE -1 END book_day,
  COUNT(*) callers
FROM caller c LEFT JOIN crm ON crm.ph10=c.ph10 LEFT JOIN bka b ON b.pid=c.pid LEFT JOIN fl ON fl.ph10=c.ph10
GROUP BY 1,2,3,4,5,6;
""".replace("{floor}", FLOOR)

VINT_SQL = """
WITH caller AS (SELECT pid, call_wk, ph10, fcts FROM (
    SELECT ec.user_id pid, DATE_TRUNC('week',DATEADD(minute,330,ec.created_at))::date call_wk, RIGHT(p.phone_no,10) ph10,
      DATEADD(minute,330,ec.created_at) fcts,
      ROW_NUMBER() OVER (PARTITION BY ec.user_id, DATE_TRUNC('week',DATEADD(minute,330,ec.created_at)) ORDER BY ec.created_at) rn
    FROM allo_prod.allo_vendors.exotel_calls ec JOIN allo_prod.allo_persons.patient p ON p.id=ec.user_id
    WHERE ec.direction IN ('inbound','incoming') AND ec.routed_to='lead_to_call' AND ec.exotel_number!='08071176846'
      AND ec.user_id IS NOT NULL AND DATE_TRUNC('week',DATEADD(minute,330,ec.created_at))::date>='{floor}') WHERE rn=1),
 fl AS (SELECT RIGHT(phone_no1,10) ph10, DATE_TRUNC('week',MIN(created_on_date))::date flw FROM production.public.main_source_wise_leads GROUP BY 1),
 bka AS (SELECT patient_id pid, MIN(DATEADD(minute,330,created_at)) bts FROM allo_prod.allo_consultations.appointments WHERE deleted_at IS NULL GROUP BY 1)
SELECT TO_CHAR(c.call_wk,'YYYY-MM-DD') week,
  CASE WHEN fl.flw IS NULL THEN 'no_lead' WHEN fl.flw<c.call_wk THEN 'earlier' ELSE 'this_wk' END vintage,
  DATEDIFF(day, c.call_wk, c.fcts::date) call_day,
  CASE WHEN b.bts IS NOT NULL AND DATE_TRUNC('week',b.bts)::date=c.call_wk THEN DATEDIFF(day, c.call_wk, b.bts::date) ELSE -1 END book_day,
  COUNT(*) callers
FROM caller c LEFT JOIN fl ON fl.ph10=c.ph10 LEFT JOIN bka b ON b.pid=c.pid GROUP BY 1,2,3,4;
""".replace("{floor}", FLOOR)

LEADS_SQL = """
WITH lead1 AS (SELECT RIGHT(phone_no1,10) ph10, MIN(created_on_date) fd FROM production.public.main_source_wise_leads GROUP BY 1)
SELECT TO_CHAR(DATE_TRUNC('week', fd)::date,'YYYY-MM-DD') week,
  DATEDIFF(day, DATE_TRUNC('week', fd)::date, fd) create_day, COUNT(*) new_leads
FROM lead1 WHERE fd >= '{floor}' GROUP BY 1,2;
""".replace("{floor}", FLOOR)


def run(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True,
                       env={**os.environ, "AWS_PROFILE": "redshift-data"})
    out = (p.stdout or "").strip()
    if p.returncode != 0 or out.startswith("FAIL") or "Traceback" in (p.stderr or ""):
        sys.exit("query failed:\n" + (p.stderr or out)[-800:])
    return [ln.split("\t") for ln in out.split("\n") if ln.strip() and not ln.startswith("FAIL")]


def norm(s):
    s = (s or "").lower()
    return {"gmb": "GMB", "google": "Google Ads", "fb": "Meta", "practo": "Practo",
            "justdial": "JustDial", "organic": "Organic"}.get(s, "(none)" if s in ("(none)", "", "null") else "Other")


def cell():
    return {"cal": [0] * 7, "bkd": [0] * 7}


def add(store, wk, key, cd, bd, n):
    c = store[wk].setdefault(key, cell())
    if 0 <= cd < 7:
        c["cal"][cd] += n
    if 0 <= bd < 7:
        c["bkd"][bd] += n


if __name__ == "__main__":
    ov = {r["exotel_number"].strip(): r["channel"].strip() for r in csv.DictReader(open(OVR))}
    chan = defaultdict(dict); prov = defaultdict(dict); vint = defaultdict(dict)
    sysc = defaultdict(dict); sysc_tw = defaultdict(dict)   # raw system (all) + this-week-lead only
    for r in run(RES_SQL):
        if len(r) < 7:
            continue
        wk, num, crm, vintage, cd, bd, n = r[0], r[1].strip(), r[2], r[3], int(float(r[4])), int(float(r[5])), int(float(r[6]))
        sysch = norm(crm)
        rawch = sysch if sysch != "(none)" else "Direct / Call (blank)"
        add(sysc, wk, rawch, cd, bd, n)                 # RAW system utm_source (uncorrected), all callers
        if vintage == "this_wk":
            add(sysc_tw, wk, rawch, cd, bd, n)          # RAW system, this-week-lead callers only (→ 1,626)
        if num in ov:
            final = ov[num]; pv = "corrected" if final != sysch else "confirmed"
        elif sysch != "(none)":
            final, pv = sysch, "system"
        else:
            final, pv = "Undetermined", "unclassified"
        add(chan, wk, final, cd, bd, n)
        add(prov, wk, pv, cd, bd, n)
    for r in run(VINT_SQL):
        if len(r) < 5:
            continue
        wk, v, cd, bd, n = r[0], r[1], int(float(r[2])), int(float(r[3])), int(float(r[4]))
        add(vint, wk, v, cd, bd, n)
    leadsnew = defaultdict(lambda: [0] * 7)
    for r in run(LEADS_SQL):
        if len(r) < 3:
            continue
        wk, cd, n = r[0], int(float(r[1])), int(float(r[2]))
        if 0 <= cd < 7:
            leadsnew[wk][cd] += n
    weeks = sorted(set(list(chan) + list(vint) + list(leadsnew)))
    json.dump({"weeks": weeks, "chan": chan, "sys": sysc, "sys_tw": sysc_tw, "prov": prov, "vint": vint, "leadsnew": leadsnew},
              open(OUT, "w"), separators=(",", ":"))
    for wk in weeks[-3:]:
        tc = sum(sum(chan[wk][c]["cal"]) for c in chan[wk]); tb = sum(sum(chan[wk][c]["bkd"]) for c in chan[wk])
        print("%s full-week callers %d booked %d" % (wk, tc, tb))
    print("wrote", OUT)
