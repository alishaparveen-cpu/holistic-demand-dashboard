#!/usr/bin/env python3
"""Build data_sc_calendar.json — the founder's day-on-day SC calendar for a clinic × week.

Goal: separate "lead→book didn't happen because of AVAILABILITY" from "…because of LEAD QUALITY".

Two halves, per clinic, per day of the last complete Mon–Sun week:
  A. SC BOOKINGS (matches the clinician calendar) — count of Screening-Call appointments scheduled
     that day at the clinic, split by the LEAD AGE at booking (same-day / 1d / 2d / 3-7d / 8d+ / no-lead),
     and by status (Completed·Scheduled / No-Show / Rescheduled·Cancelled).
  B. LEADS THAT CAME (calls to the clinic's own numbers) that day — connected / wanted-to-book (AI intent)
     / connected-but-no-book-intent / not-connected.

Read A against your clinician calendar (should tie). Read A vs B to see: on a day with lots of leads
but few bookings, did the leads want to book (→ availability/ops) or not (→ lead quality)?

Run: AWS_PROFILE=redshift-data python3 scripts/build_sc_calendar.py
"""
import os, sys, json, subprocess, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def q(sql):
    p = subprocess.run([sys.executable, os.path.join(ROOT,"scripts","redshift_query.py")], input=sql, capture_output=True, text=True)
    if p.returncode!=0 or "ERROR" in (p.stderr or ""): sys.stderr.write("query failed:\n"+(p.stderr or "")[:600]+"\n"); sys.exit(1)
    return [l.split("\t") for l in p.stdout.strip().splitlines() if l.strip()]

# clinics: locality+city for the booking side; clinic-OWN call numbers for the leads side (exclude shared paid → clean attribution)
CLINICS = [
  {"key":"coimbatore","disp":"Bharathi Nagar · Coimbatore","city":"Coimbatore","loc":"Bharathi Nagar","nums":["4440114608","4440116568","4440114631"]},
  {"key":"whitefield","disp":"Whitefield · Bangalore","city":"Bangalore","loc":"Whitefield","nums":["8047280292"]},
]
BOOK_INTENT = ("BOOK_APPOINTMENT","BOOK_SLOT","BOOK_TEST","NEEDS_TESTS","NEEDS_MEDS")

# last COMPLETE Mon–Sun week (IST)
today = datetime.date.today()
mon = today - datetime.timedelta(days=today.weekday())     # this week's Monday
start = mon - datetime.timedelta(days=7)                    # last week's Monday
end = start + datetime.timedelta(days=7)                    # exclusive
DAYS = [(start+datetime.timedelta(days=i)).isoformat() for i in range(7)]
S, E = start.isoformat(), end.isoformat()

def bkey(age):
    if age is None: return "no_lead"
    if age<=0: return "same_day"
    if age==1: return "d1"
    if age==2: return "d2"
    if age<=7: return "d3_7"
    return "d8plus"

out = {"_meta":{"days":DAYS, "week":f"{S}→{(end-datetime.timedelta(days=1)).isoformat()}",
        "age_buckets":["same_day","d1","d2","d3_7","d8plus","no_lead"],
        "age_label":{"same_day":"Same-day lead","d1":"1-day-old","d2":"2-day-old","d3_7":"3–7-day-old","d8plus":"8-day+ old","no_lead":"No lead matched"},
        "note":"SC bookings = Screening-Call appts scheduled that day at the clinic (all statuses = the calendar). Lead age = booking-made − lead-first-seen. Leads = calls to the clinic's own numbers; connected=answered; wanted_book=AI book-intent."},
       "clinics":{}}

for c in CLINICS:
    # ---- A) SC bookings per day × lead-age × status ----
    a = q(f"""
    WITH lead1 AS (SELECT RIGHT(phone_no,10) ph, MIN(created_at) lead_dt FROM allo_persons.lead WHERE deleted_at IS NULL GROUP BY 1)
    SELECT DATE(a.start_time + INTERVAL '5 hours 30 minutes') d,
      CASE WHEN a.status IN ('COMPLETED','RECONSULTED','SCHEDULED') THEN 'live'
           WHEN a.status='MISSED' THEN 'noshow' ELSE 'released' END st,   -- MISSED = no-show; RESCHEDULED/CANCELLED = released
      DATEDIFF(day, DATE(l.lead_dt + INTERVAL '5 hours 30 minutes'), DATE(a.created_at + INTERVAL '5 hours 30 minutes')) age,
      COUNT(*) n
    FROM allo_consultations.appointments a
    JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
    JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.deleted_at IS NULL AND loc.locality='{c['loc']}' AND loc.city='{c['city']}'
    JOIN allo_persons.patient p ON p.id=a.patient_id
    LEFT JOIN lead1 l ON l.ph=RIGHT(p.phone_no,10)
    WHERE a.deleted_at IS NULL AND (a.start_time + INTERVAL '5 hours 30 minutes')>='{S}' AND (a.start_time + INTERVAL '5 hours 30 minutes')<'{E}'
    GROUP BY 1,2,3""")
    days = {d:{"sc":0,"by_age":{k:0 for k in out["_meta"]["age_buckets"]},
               "by_status":{"live":0,"noshow":0,"released":0},
               "age_status":{k:{"live":0,"noshow":0,"released":0} for k in out["_meta"]["age_buckets"]}} for d in DAYS}
    for r in a:
        d, st = r[0], r[1]; age = None if (len(r)<4 or r[2] in ("","\\N",None)) else int(float(r[2])); n=int(float(r[3]))
        if d not in days: continue
        k=bkey(age); days[d]["sc"]+=n; days[d]["by_age"][k]+=n; days[d]["by_status"][st]+=n; days[d]["age_status"][k][st]+=n
    # ---- B) leads (calls to the clinic's own numbers) per day: connected / wanted-book ----
    nums = "','".join(c["nums"])
    b = q(f"""
    SELECT DATE(ec.start_time + INTERVAL '5 hours 30 minutes') d,
      COUNT(DISTINCT RIGHT(COALESCE(ec."from",''),10)) leads,
      COUNT(DISTINCT CASE WHEN ec.status='completed' THEN RIGHT(COALESCE(ec."from",''),10) END) connected,
      COUNT(DISTINCT CASE WHEN ca.analysis.user_intent.result::varchar IN ('{"','".join(BOOK_INTENT)}') THEN RIGHT(COALESCE(ec."from",''),10) END) wanted_book
    FROM allo_vendors.exotel_calls ec
    LEFT JOIN allo_analytics.call_analyses ca ON ca.call_id=ec.call_id
    WHERE RIGHT(ec.exotel_number,10) IN ('{nums}') AND ec.routed_to='lead_to_call'
      AND (ec.start_time + INTERVAL '5 hours 30 minutes')>='{S}' AND (ec.start_time + INTERVAL '5 hours 30 minutes')<'{E}'
    GROUP BY 1""")
    for d in days: days[d]["leads"]={"total":0,"connected":0,"wanted_book":0}
    for r in b:
        d=r[0]
        if d not in days: continue
        days[d]["leads"]={"total":int(float(r[1])),"connected":int(float(r[2])),"wanted_book":int(float(r[3]))}
    out["clinics"][c["key"]]={"disp":c["disp"],"city":c["city"],"loc":c["loc"],"days":days}
    tot=sum(days[d]["sc"] for d in DAYS); sd=sum(days[d]["by_age"]["same_day"] for d in DAYS)
    ld=sum(days[d]["leads"]["total"] for d in DAYS); wb=sum(days[d]["leads"]["wanted_book"] for d in DAYS)
    print(f"{c['key']:<11} week {out['_meta']['week']}: {tot} SC bookings ({sd} same-day-lead) · {ld} call leads ({wb} wanted to book)")

json.dump(out, open(os.path.join(ROOT,"data_sc_calendar.json"),"w"), separators=(",",":"))
print("wrote data_sc_calendar.json")
