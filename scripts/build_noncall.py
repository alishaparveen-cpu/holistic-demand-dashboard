#!/usr/bin/env python3
"""Parallel funnel — NON-CALL leads (this-week new leads that did NOT place an inbound call),
DAY-of-week granular (for week-to-date compare).

Source = CRM utm_source × utm_medium. WhatsApp split out of organic; website pages, internal
(retool) flagged. Booked = booked an appointment the same week WITHOUT calling.

Every metric = two 7-slot arrays (0=Mon..6=Sun): cal[d] leads by lead-create day, bkd[d] booked
by booking day. newtot[wk][d] = ALL new leads by create-day (called+nocall) for the denominator.

Emits data_noncall.json: weeks, src{wk:{channel:{cal[7],bkd[7]}}}, newtot{wk:[7]}
Run: AWS_PROFILE=redshift-data python3 scripts/build_noncall.py
"""
import os, sys, json, subprocess
from collections import defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
OUT = os.path.join(ROOT, "data_noncall.json")
FLOOR = "2026-04-13"   # ~12 complete weeks of history for the up-to-10-week toggle

SQL = """
WITH lead1 AS (SELECT RIGHT(phone_no1,10) ph10, MIN(created_on_date) fd FROM production.public.main_source_wise_leads GROUP BY 1),
 le AS (SELECT ph10, fd, DATE_TRUNC('week',fd)::date lwk, DATEDIFF(day, DATE_TRUNC('week',fd)::date, fd) cday FROM lead1),
 called AS (SELECT DISTINCT RIGHT(p.phone_no,10) ph10, DATE_TRUNC('week',DATEADD(minute,330,ec.created_at))::date cwk
   FROM allo_prod.allo_vendors.exotel_calls ec JOIN allo_prod.allo_persons.patient p ON p.id=ec.user_id
   WHERE ec.direction IN ('inbound','incoming') AND ec.routed_to='lead_to_call' AND ec.exotel_number!='08071176846' AND ec.user_id IS NOT NULL),
 crm AS (SELECT ph10, us, um FROM (SELECT RIGHT(phone_no,10) ph10, LOWER(CAST(utm_source AS VARCHAR)) us, LOWER(CAST(utm_medium AS VARCHAR)) um,
          ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY updated_at DESC NULLS LAST) rn
        FROM allo_prod.allo_persons.lead WHERE phone_no IS NOT NULL) WHERE rn=1),
 bkp AS (SELECT ph10, bts FROM (SELECT RIGHT(p.phone_no,10) ph10, MIN(DATEADD(minute,330,a.created_at)) bts
        FROM allo_prod.allo_consultations.appointments a JOIN allo_prod.allo_persons.patient p ON p.id=a.patient_id
        WHERE a.deleted_at IS NULL GROUP BY 1) x)
SELECT TO_CHAR(le.lwk,'YYYY-MM-DD') week,
  CASE WHEN cw.ph10 IS NULL THEN 'nocall' ELSE 'called' END grp,
  COALESCE(crm.us,'(none)') us, COALESCE(NULLIF(crm.um,''),'') um,
  le.cday create_day,
  CASE WHEN b.bts IS NOT NULL AND DATE_TRUNC('week',b.bts)::date=le.lwk THEN DATEDIFF(day, le.lwk, b.bts::date) ELSE -1 END book_day,
  COUNT(*) leads
FROM le LEFT JOIN called cw ON cw.ph10=le.ph10 AND cw.cwk=le.lwk
LEFT JOIN crm ON crm.ph10=le.ph10 LEFT JOIN bkp b ON b.ph10=le.ph10
WHERE le.lwk>='{floor}' GROUP BY 1,2,3,4,5,6;
""".replace("{floor}", FLOOR)

WEB_MEDIUMS = {"clinic", "home", "doctor", "slots", "std-testing", "sexologist", "sexologists",
               "treatment", "sti", "diagnostics", "chatbot", "assessment", "blog", "healthfeed", "login", "homepage"}


def run(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True,
                       env={**os.environ, "AWS_PROFILE": "redshift-data"})
    out = (p.stdout or "").strip()
    if p.returncode != 0 or out.startswith("FAIL") or "Traceback" in (p.stderr or ""):
        sys.exit("query failed:\n" + (p.stderr or out)[-800:])
    return [ln.split("\t") for ln in out.split("\n") if ln.strip() and not ln.startswith("FAIL")]


def chan(us, um):
    us = (us or "").lower(); um = (um or "").lower()
    if "retool" in um:
        return "Internal (staff tool)"
    if us == "organic":
        if um == "whatsapp":
            return "WhatsApp"
        if um in WEB_MEDIUMS:
            return "Website"
        return "Organic (other)"
    return {"gmb": "GMB", "google": "Google Ads", "fb": "Meta", "ig": "Meta", "practo": "Practo",
            "justdial": "JustDial"}.get(us, "(no source)" if us in ("(none)", "", "null") else "Other")


if __name__ == "__main__":
    src = defaultdict(lambda: defaultdict(lambda: {"cal": [0] * 7, "bkd": [0] * 7}))
    newtot = defaultdict(lambda: [0] * 7)
    for r in run(SQL):
        if len(r) < 7:
            continue
        wk, grp, us, um, cd, bd, n = r[0], r[1], r[2], r[3], int(float(r[4])), int(float(r[5])), int(float(r[6]))
        if 0 <= cd < 7:
            newtot[wk][cd] += n
        if grp != "nocall":
            continue
        c = src[wk][chan(us, um)]
        if 0 <= cd < 7:
            c["cal"][cd] += n
        if 0 <= bd < 7:
            c["bkd"][bd] += n
    weeks = sorted(newtot.keys())
    json.dump({"weeks": weeks, "src": src, "newtot": newtot}, open(OUT, "w"), separators=(",", ":"))
    for wk in weeks[-3:]:
        tl = sum(sum(src[wk][c]["cal"]) for c in src[wk]); tb = sum(sum(src[wk][c]["bkd"]) for c in src[wk])
        print("%s new %d | didnt-call %d booked-online %d" % (wk, sum(newtot[wk]), tl, tb))
    print("wrote", OUT)
