#!/usr/bin/env python3
"""Build data_sc_calendar.json — founder day-on-day SC calendar for a clinic × week.

Separates "lead→book didn't happen because of AVAILABILITY" from "…because of LEAD QUALITY".

Per clinic, per day of the last complete Mon–Sun week:
  A. SC BOOKINGS (= the clinician calendar) — every Screening-Call appt scheduled that day, as a
     per-booking list: {p:full phone, pid:patient-UUID, doc:doctor, age:exact lead→booking days,
     src, med, st}. st = done(COMPLETED/RECONSULTED) · sched(SCHEDULED) · noshow(MISSED) ·
     released(RESCHEDULED/CANCELLED). Source/Medium from the patient's earliest lead's utm/origin.
     `doctors` list per clinic drives the doctor filter (ties the view to one clinician's calendar).
  B. LEADS (ALL sources, attributed to the clinic by lead.location code) that day, per-lead:
     {p:full phone, src, med, conn:did-we-connect, want:AI-wanted-book, booked:did-they-get-an-SC,
     rec:call recording URL, dur:call seconds}. Call outcome + recording joined from the clinic's
     own exotel numbers (routed_to='lead_to_call').

Run: AWS_PROFILE=redshift-data python3 scripts/build_sc_calendar.py
"""
import os, sys, json, subprocess, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IST = "INTERVAL '5 hours 30 minutes'"
def q(sql):
    p = subprocess.run([sys.executable, os.path.join(ROOT,"scripts","redshift_query.py")], input=sql, capture_output=True, text=True)
    if p.returncode!=0 or "ERROR" in (p.stderr or ""): sys.stderr.write("query failed:\n"+(p.stderr or "")[:800]+"\n"); sys.exit(1)
    return [l.split("\t") for l in p.stdout.strip().splitlines() if l.strip()]

# clinics: locality+city for bookings; lead.location code for all-source leads; own call numbers for call outcome/recording
CLINICS = [
  {"key":"coimbatore","disp":"Bharathi Nagar · Coimbatore","city":"Coimbatore","loc":"Bharathi Nagar",
   "code":"TN_CMBTRE","nums":["4440114608","4440116568","4440114631"]},
  {"key":"whitefield","disp":"Whitefield · Bangalore","city":"Bangalore","loc":"Whitefield",
   "code":"BLR_WTF","nums":["8047280292"]},
]
BOOK_INTENT = ("BOOK_APPOINTMENT","BOOK_SLOT","BOOK_TEST","NEEDS_TESTS","NEEDS_MEDS")

# lead source/medium classification (from lead.utm_source/gclid/fbclid + lead.origin) — verified live 2026-08-03
def SRC(a): return f"""CASE
  WHEN {a}.gclid IS NOT NULL OR {a}.utm_source ILIKE 'google' THEN 'Google'
  WHEN {a}.fbclid IS NOT NULL OR {a}.fbc IS NOT NULL OR {a}.utm_source ILIKE 'fb' OR {a}.utm_source ILIKE '%facebook%' OR {a}.utm_source ILIKE '%meta%' THEN 'Meta'
  WHEN {a}.utm_source ILIKE 'gmb' THEN 'GMB'
  WHEN {a}.utm_source ILIKE 'practo' THEN 'Practo'
  WHEN {a}.utm_source ILIKE 'organic' THEN 'Organic'
  WHEN {a}.utm_source ILIKE '%walkin%' OR {a}.origin ILIKE 'retool' THEN 'Walk-in'
  WHEN {a}.utm_source IS NULL OR {a}.utm_source='' THEN 'Direct/unknown'
  ELSE {a}.utm_source END"""
def MED(a): return f"""CASE
  WHEN {a}.origin ILIKE 'exotel' THEN 'Call'
  WHEN {a}.origin ILIKE 'whatsapp' THEN 'WhatsApp'
  WHEN {a}.origin ILIKE 'practo' THEN 'Practo'
  WHEN {a}.origin ILIKE 'retool' OR {a}.utm_source ILIKE '%walkin%' THEN 'Walk-in'
  WHEN {a}.origin IS NULL OR {a}.origin='' THEN 'Web'
  ELSE 'Web' END"""

today = datetime.date.today()
mon = today - datetime.timedelta(days=today.weekday())
start = mon - datetime.timedelta(days=7); end = start + datetime.timedelta(days=7)
DAYS = [(start+datetime.timedelta(days=i)).isoformat() for i in range(7)]
S, E = start.isoformat(), end.isoformat()

out = {"_meta":{"days":DAYS, "week":f"{S}→{(end-datetime.timedelta(days=1)).isoformat()}",
        "note":"① SC bookings = Screening-Call appts scheduled that day at the clinic (all statuses = the clinician calendar). done=COMPLETED/RECONSULTED. age = booking-made − lead-first-seen (exact). src/med from the patient's earliest lead. ② Leads = ALL leads attributed to the clinic by lead.location code, per-lead; conn/want/recording from the clinic's own call lines (lead_to_call). ①source & ②source use different attribution (patient's earliest lead vs clinic code) so they won't perfectly reconcile."},
       "clinics":{}}

for c in CLINICS:
    # ---- A) per-booking rows ----
    a = q(f"""
    WITH lead1 AS (SELECT RIGHT(phone_no,10) ph, MIN(created_at) lead_dt FROM allo_persons.lead WHERE deleted_at IS NULL GROUP BY 1)
    SELECT DATE(a.start_time + {IST}) d,
      p.phone_no phone, p.id pid, COALESCE(pr.name,'Unassigned') doc,
      DATEDIFF(day, DATE(l.lead_dt + {IST}), DATE(a.created_at + {IST})) age,
      {SRC('ld')} src, {MED('ld')} med,
      CASE WHEN a.status IN ('COMPLETED','RECONSULTED') THEN 'done'
           WHEN a.status='SCHEDULED' THEN 'sched'
           WHEN a.status='MISSED' THEN 'noshow' ELSE 'released' END st
    FROM allo_consultations.appointments a
    JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
    JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.deleted_at IS NULL AND loc.locality='{c['loc']}' AND loc.city='{c['city']}'
    JOIN allo_persons.patient p ON p.id=a.patient_id
    LEFT JOIN allo_persons.providers pr ON pr.id=a.provider_id
    LEFT JOIN lead1 l ON l.ph=RIGHT(p.phone_no,10)
    LEFT JOIN allo_persons.lead ld ON RIGHT(ld.phone_no,10)=l.ph AND ld.created_at=l.lead_dt AND ld.deleted_at IS NULL
    WHERE a.deleted_at IS NULL AND (a.start_time + {IST})>='{S}' AND (a.start_time + {IST})<'{E}'
    """)
    days = {d:{"bookings":[], "leads":[]} for d in DAYS}
    docs=set()
    for r in a:
        d=r[0]
        if d not in days: continue
        age = None if (len(r)<5 or r[4] in ("","\\N",None)) else int(float(r[4]))
        doc=r[3] or "Unassigned"; docs.add(doc)
        days[d]["bookings"].append({"p":r[1], "pid":(r[2] or ""), "doc":doc, "age":age,
                                    "src":(r[5] or "Direct/unknown"), "med":(r[6] or "Web"), "st":r[7]})
    # ---- B) per-lead rows (all sources by clinic code) + call outcome/recording + booked flag ----
    nums = "','".join(c["nums"])
    b = q(f"""
    WITH scbk AS (
      SELECT DISTINCT RIGHT(p.phone_no,10) ph
      FROM allo_consultations.appointments a
      JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
      JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.locality='{c['loc']}' AND loc.city='{c['city']}'
      JOIN allo_persons.patient p ON p.id=a.patient_id
      WHERE a.deleted_at IS NULL AND (a.start_time + {IST})>='{S}' AND (a.start_time + {IST})<'{E}'),
    callout AS (
      SELECT RIGHT(ec."from",10) ph, DATE(ec.start_time + {IST}) d,
        MAX(CASE WHEN ec.status='completed' THEN 1 ELSE 0 END) conn,
        MAX(CASE WHEN ca.analysis.user_intent.result::varchar IN ('{"','".join(BOOK_INTENT)}') THEN 1 ELSE 0 END) want,
        MAX(NULLIF(ec.recording_url,'')) rec, MAX(ec.total_duration) dur
      FROM allo_vendors.exotel_calls ec
      LEFT JOIN allo_analytics.call_analyses ca ON ca.call_id=ec.call_id
      WHERE RIGHT(ec.exotel_number,10) IN ('{nums}') AND ec.routed_to='lead_to_call'
        AND (ec.start_time + {IST})>='{S}' AND (ec.start_time + {IST})<'{E}'
      GROUP BY 1,2)
    SELECT DATE(ld.created_at + {IST}) d, ld.phone_no phone, {SRC('ld')} src, {MED('ld')} med,
      COALESCE(co.conn,0) conn, COALESCE(co.want,0) want,
      CASE WHEN sb.ph IS NOT NULL THEN 1 ELSE 0 END booked,
      COALESCE(co.rec,'') rec, COALESCE(co.dur,0) dur
    FROM allo_persons.lead ld
    LEFT JOIN callout co ON co.ph=RIGHT(ld.phone_no,10) AND co.d=DATE(ld.created_at + {IST})
    LEFT JOIN scbk sb ON sb.ph=RIGHT(ld.phone_no,10)
    WHERE ld.deleted_at IS NULL AND ld.location='{c['code']}'
      AND (ld.created_at + {IST})>='{S}' AND (ld.created_at + {IST})<'{E}'
    """)
    for r in b:
        d=r[0]
        if d not in days: continue
        days[d]["leads"].append({"p":r[1], "src":(r[2] or "Direct/unknown"), "med":(r[3] or "Web"),
                                 "conn":int(r[4]), "want":int(r[5]), "booked":int(r[6]),
                                 "rec":(r[7] or ""), "dur":int(float(r[8] or 0))})
    out["clinics"][c["key"]]={"disp":c["disp"],"city":c["city"],"loc":c["loc"],
                              "doctors":sorted(docs),"days":days}
    tot=sum(len(days[d]["bookings"]) for d in DAYS)
    done=sum(1 for d in DAYS for bk in days[d]["bookings"] if bk["st"]=="done")
    sd=sum(1 for d in DAYS for bk in days[d]["bookings"] if bk["age"]==0)
    ld=sum(len(days[d]["leads"]) for d in DAYS)
    print(f"{c['key']:<11} {out['_meta']['week']}: {tot} SC bookings ({done} done, {sd} same-day-lead) · {ld} leads · docs={sorted(docs)}")

json.dump(out, open(os.path.join(ROOT,"data_sc_calendar.json"),"w"), separators=(",",":"))
print("wrote data_sc_calendar.json")
