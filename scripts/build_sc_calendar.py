#!/usr/bin/env python3
"""Build data_sc_calendar.json — founder day-on-day SC calendar for a clinic × week,
with EXACT lead-age (0–7d, 8+), per-BOOKING source/medium detail, and per-day leads by source.

Goal: separate "lead→book didn't happen because of AVAILABILITY" from "…because of LEAD QUALITY".

Per clinic, per day of the last complete Mon–Sun week:
  A. SC BOOKINGS (= the clinician calendar) — every Screening-Call appt scheduled that day, as a
     per-booking list: {p:phone-last4, age:exact days lead→booking, src, med, st}. Age bucketed
     exact 0..7 then 8+ / no-lead. Source = GMB/Google/Meta/Practo/Organic/Walk-in (from the lead's
     utm); Medium = Call/Web/WhatsApp/Practo/Walk-in (from the lead's origin). Status live/noshow/released.
  B. LEADS (calls to the clinic's own numbers) that day, by source (which number): total / connected
     (answered) / wanted-to-book (AI call-audit book-intent).

Run: AWS_PROFILE=redshift-data python3 scripts/build_sc_calendar.py
"""
import os, sys, json, subprocess, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def q(sql):
    p = subprocess.run([sys.executable, os.path.join(ROOT,"scripts","redshift_query.py")], input=sql, capture_output=True, text=True)
    if p.returncode!=0 or "ERROR" in (p.stderr or ""): sys.stderr.write("query failed:\n"+(p.stderr or "")[:600]+"\n"); sys.exit(1)
    return [l.split("\t") for l in p.stdout.strip().splitlines() if l.strip()]

# clinics: locality+city for bookings; own call numbers (→ source) for the leads side
CLINICS = [
  {"key":"coimbatore","disp":"Bharathi Nagar · Coimbatore","city":"Coimbatore","loc":"Bharathi Nagar",
   "num_src":{"4440114608":"GMB","4440116568":"GMB","4440114631":"Google"}},
  {"key":"whitefield","disp":"Whitefield · Bangalore","city":"Bangalore","loc":"Whitefield",
   "num_src":{"8047280292":"GMB"}},
]
BOOK_INTENT = ("BOOK_APPOINTMENT","BOOK_SLOT","BOOK_TEST","NEEDS_TESTS","NEEDS_MEDS")

# lead source/medium classification (from lead.utm_source / lead.origin) — verified live 2026-08-03
SRC_SQL = """CASE
  WHEN ld.gclid IS NOT NULL OR ld.utm_source ILIKE 'google' THEN 'Google'
  WHEN ld.fbclid IS NOT NULL OR ld.fbc IS NOT NULL OR ld.utm_source ILIKE 'fb' OR ld.utm_source ILIKE '%facebook%' OR ld.utm_source ILIKE '%meta%' THEN 'Meta'
  WHEN ld.utm_source ILIKE 'gmb' THEN 'GMB'
  WHEN ld.utm_source ILIKE 'practo' THEN 'Practo'
  WHEN ld.utm_source ILIKE 'organic' THEN 'Organic'
  WHEN ld.utm_source ILIKE '%walkin%' OR ld.origin ILIKE 'retool' THEN 'Walk-in'
  WHEN ld.utm_source IS NULL OR ld.utm_source='' THEN 'Direct/unknown'
  ELSE ld.utm_source END"""
MED_SQL = """CASE
  WHEN ld.origin ILIKE 'exotel' THEN 'Call'
  WHEN ld.origin ILIKE 'whatsapp' THEN 'WhatsApp'
  WHEN ld.origin ILIKE 'practo' THEN 'Practo'
  WHEN ld.origin ILIKE 'retool' OR ld.utm_source ILIKE '%walkin%' THEN 'Walk-in'
  WHEN ld.origin IS NULL OR ld.origin='' THEN 'Web'
  ELSE 'Web' END"""

today = datetime.date.today()
mon = today - datetime.timedelta(days=today.weekday())
start = mon - datetime.timedelta(days=7); end = start + datetime.timedelta(days=7)
DAYS = [(start+datetime.timedelta(days=i)).isoformat() for i in range(7)]
S, E = start.isoformat(), end.isoformat()

out = {"_meta":{"days":DAYS, "week":f"{S}→{(end-datetime.timedelta(days=1)).isoformat()}",
        "note":"SC bookings = Screening-Call appts scheduled that day at the clinic (all statuses = the clinician calendar). age = booking-made − lead-first-seen (exact days). src/med from the lead's utm/origin. Leads = calls to the clinic's own numbers; connected=answered; wanted_book=AI book-intent (undercount)."},
       "clinics":{}}

for c in CLINICS:
    # ---- A) per-booking rows: day, phone-last4, exact lead age, source, medium, status ----
    a = q(f"""
    WITH lead1 AS (SELECT RIGHT(phone_no,10) ph, MIN(created_at) lead_dt FROM allo_persons.lead WHERE deleted_at IS NULL GROUP BY 1)
    SELECT DATE(a.start_time + INTERVAL '5 hours 30 minutes') d,
      RIGHT(p.phone_no,4) p4,
      DATEDIFF(day, DATE(l.lead_dt + INTERVAL '5 hours 30 minutes'), DATE(a.created_at + INTERVAL '5 hours 30 minutes')) age,
      p.id pid,
      {SRC_SQL} src, {MED_SQL} med,
      CASE WHEN a.status IN ('COMPLETED','RECONSULTED','SCHEDULED') THEN 'live' WHEN a.status='MISSED' THEN 'noshow' ELSE 'released' END st
    FROM allo_consultations.appointments a
    JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
    JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.deleted_at IS NULL AND loc.locality='{c['loc']}' AND loc.city='{c['city']}'
    JOIN allo_persons.patient p ON p.id=a.patient_id
    LEFT JOIN lead1 l ON l.ph=RIGHT(p.phone_no,10)
    LEFT JOIN allo_persons.lead ld ON RIGHT(ld.phone_no,10)=l.ph AND ld.created_at=l.lead_dt AND ld.deleted_at IS NULL
    WHERE a.deleted_at IS NULL AND (a.start_time + INTERVAL '5 hours 30 minutes')>='{S}' AND (a.start_time + INTERVAL '5 hours 30 minutes')<'{E}'
    """)
    days = {d:{"bookings":[]} for d in DAYS}
    for r in a:
        d=r[0]
        if d not in days: continue
        age = None if (len(r)<3 or r[2] in ("","\\N",None)) else int(float(r[2]))
        days[d]["bookings"].append({"p":r[1], "pid":(r[3] or ""), "age":age, "src":(r[4] or "Direct/unknown"), "med":(r[5] or "Web"), "st":r[6]})
    # ---- B) leads by source (calls to the clinic's own numbers) ----
    nums = "','".join(c["num_src"].keys())
    b = q(f"""
    SELECT DATE(ec.start_time + INTERVAL '5 hours 30 minutes') d, RIGHT(ec.exotel_number,10) num,
      COUNT(DISTINCT RIGHT(COALESCE(ec."from",''),10)) leads,
      COUNT(DISTINCT CASE WHEN ec.status='completed' THEN RIGHT(COALESCE(ec."from",''),10) END) connected,
      COUNT(DISTINCT CASE WHEN ca.analysis.user_intent.result::varchar IN ('{"','".join(BOOK_INTENT)}') THEN RIGHT(COALESCE(ec."from",''),10) END) wanted_book
    FROM allo_vendors.exotel_calls ec
    LEFT JOIN allo_analytics.call_analyses ca ON ca.call_id=ec.call_id
    WHERE RIGHT(ec.exotel_number,10) IN ('{nums}') AND ec.routed_to='lead_to_call'
      AND (ec.start_time + INTERVAL '5 hours 30 minutes')>='{S}' AND (ec.start_time + INTERVAL '5 hours 30 minutes')<'{E}'
    GROUP BY 1,2""")
    for d in days: days[d]["leads_by_src"]={}
    for r in b:
        d=r[0]; num=r[1]
        if d not in days: continue
        src=c["num_src"].get(num, "Call")
        e=days[d]["leads_by_src"].setdefault(src, {"leads":0,"connected":0,"wanted_book":0})
        e["leads"]+=int(float(r[2])); e["connected"]+=int(float(r[3])); e["wanted_book"]+=int(float(r[4]))
    out["clinics"][c["key"]]={"disp":c["disp"],"city":c["city"],"loc":c["loc"],"days":days}
    tot=sum(len(days[d]["bookings"]) for d in DAYS)
    sd=sum(1 for d in DAYS for bk in days[d]["bookings"] if bk["age"]==0)
    print(f"{c['key']:<11} {out['_meta']['week']}: {tot} SC bookings ({sd} same-day-lead)")

json.dump(out, open(os.path.join(ROOT,"data_sc_calendar.json"),"w"), separators=(",",":"))
print("wrote data_sc_calendar.json")
