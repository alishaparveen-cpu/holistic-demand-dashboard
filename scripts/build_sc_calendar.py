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

# clinics: auto-generated from allo_health.locations (all clinics with recent SC activity).
#   loc.locality+city → bookings/roster; loc.code → lead attribution; call numbers derived from exotel routing.
import re as _re
def slugify(city, loc): return _re.sub(r'[^a-z0-9]+','_', (loc+'_'+city).lower()).strip('_')
def digits10(s):
    d=_re.sub(r'\D','', s or '')
    return d[-10:] if len(d)>=10 else None

def get_clinics():
    # active clinics (SC activity in last 45d) with their lead-code + clinic-SPECIFIC call numbers
    # (locations.phone_no + phone_numbers JSON mhPhoneNo/altPhoneNo). Authoritative per-clinic numbers.
    rows = q("""
    SELECT DISTINCT l.city, l.locality, l.code, l.phone_no, JSON_SERIALIZE(l.phone_numbers)
    FROM allo_health.locations l
    WHERE l.deleted_at IS NULL AND l.is_active=1 AND l.locality IS NOT NULL AND l.locality!=''
      AND l.city IS NOT NULL AND l.city!='' AND l.code IS NOT NULL AND lower(l.name) NOT LIKE '%online%'
      AND EXISTS (SELECT 1 FROM allo_consultations.appointments a
                  JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
                  WHERE a.location_id=l.id AND a.deleted_at IS NULL
                    AND a.start_time >= DATEADD(day,-45,CURRENT_DATE))
    ORDER BY 1,2""")
    allc=[]
    for r in rows:
        city, loc, code, phone = r[0], r[1], r[2], (r[3] if len(r)>3 else "")
        pjson = r[4] if len(r)>4 else ""
        nums=set()
        d=digits10(phone)
        if d: nums.add(d)
        try:
            j=json.loads(pjson) if pjson and pjson not in ("null","True","") else {}
            for k in ("mhPhoneNo","altPhoneNo","phoneNo","primaryPhoneNo"):
                d=digits10(j.get(k) if isinstance(j,dict) else None)
                if d: nums.add(d)
        except Exception: pass
        allc.append({"key":slugify(city,loc), "disp":f"{loc} · {city}", "city":city, "loc":loc,
                     "code":code, "nums":sorted(nums)})
    # MH clinics only, in the requested order (matched by locality/city keyword)
    MH=[("Baner","baner"),("Hadapsar","hadapsar"),("Kharghar","kharghar"),("Coimbatore","bharathi"),
        ("Indiranagar","indiranagar"),("Whitefield","whitefield"),("Brookefield","brookefield"),
        ("Jaipur","vaishali"),("Hubli","hubli")]
    sel=[]
    for name,kw in MH:
        m=[c for c in allc if kw in (c["loc"]+" "+c["city"]).lower()]
        if m: sel.append(m[0])
        else: sys.stderr.write(f"WARN: no active clinic matched '{name}' ({kw})\n")
    return sel

CLINICS = get_clinics()
print(f"{len(CLINICS)} MH clinics: "+", ".join(c["disp"] for c in CLINICS))
BOOK_INTENT = ("BOOK_APPOINTMENT","BOOK_SLOT","BOOK_TEST","NEEDS_TESTS","NEEDS_MEDS")
SC_TYPE = "'cd02525c-1528-4047-a12c-1ad526c28c9a'"  # roster_slots SC slot type

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

NUL=("","\\N","True",None)
def g(r,i): return r[i] if i<len(r) else ""   # trailing empty cols are dropped by the tab-split
def rzn_bucket(reason):
    """Bucket an appointment reschedule/cancel reason → doctor-side (shrinkage) vs patient-side vs other."""
    r=(reason or "").lower().strip()
    if not r or r=="(no reason)": return ""
    if "doctor" in r or "nonbookable" in r or "block" in r or "provider" in r: return "doctor"
    if ("patient" in r or "i want to" in r or "cancel" in r or "change my appointment" in r
        or "book later" in r or "travel" in r or "busy" in r or "mistake" in r or "feeling better" in r): return "patient"
    return "other"
def parse_recs(*ss):
    """Parse one or more LISTAGG strings ('url~dur~date|url~dur~date') into a deduped recording list."""
    out=[]; seen=set()
    for s in ss:
        if not s or s in NUL: continue
        for item in s.split('|'):
            p=item.split('~')
            if not p or not p[0] or p[0] in NUL: continue
            if p[0] in seen: continue
            seen.add(p[0])
            out.append({"u":p[0], "d":(int(float(p[1])) if len(p)>1 and p[1] not in NUL else 0),
                        "dt":(p[2] if len(p)>2 and p[2] not in NUL else ""),
                        "dir":(p[3] if len(p)>3 and p[3] not in NUL else "in")})
    return out

# LISTAGG ALL recordings (inbound + outbound, any routed_to) keyed by the PATIENT-side number
# (inbound: patient in "from"; outbound: patient in "to"). Payload: url~dur~date~direction
def REC_LISTAGG(nums_csv, wstart):
    return f"""SELECT CASE WHEN ec.direction='inbound' THEN RIGHT(ec."from",10) ELSE RIGHT(ec."to",10) END ph,
      LISTAGG(ec.recording_url||'~'||COALESCE(ec.total_duration,0)||'~'||TO_CHAR(DATE(ec.start_time+{IST}),'YYYY-MM-DD')||'~'||COALESCE(ec.direction,'in'),'|') WITHIN GROUP (ORDER BY ec.start_time) recs
    FROM allo_vendors.exotel_calls ec
    WHERE RIGHT(ec.exotel_number,10) IN ('{nums_csv}')
      AND ec.recording_url IS NOT NULL AND ec.recording_url!=''
      AND (ec.start_time + {IST})>='{wstart}' AND (ec.start_time + {IST})<'{E}' GROUP BY 1"""

# AI call-audit category (diagnoses.category) + summary per caller number — real category wins, else longest call.
# summary sanitized of tabs/newlines so it survives the tab-separated query output.
def META_BYPHONE(nums_csv, wstart):
    return f"""SELECT ph, cat, summ FROM (
      SELECT RIGHT(ec."from",10) ph, ca.analysis.diagnoses.category::varchar cat,
        REPLACE(REPLACE(REPLACE(ca.analysis.summary::varchar,CHR(9),' '),CHR(10),' '),CHR(13),' ') summ,
        ROW_NUMBER() OVER (PARTITION BY RIGHT(ec."from",10)
          ORDER BY (CASE WHEN ca.analysis.diagnoses.category::varchar NOT IN ('NOT_MENTIONED','OTHER') AND ca.analysis.diagnoses.category IS NOT NULL THEN 1 ELSE 0 END) DESC, ec.total_duration DESC NULLS LAST) rn
      FROM allo_vendors.exotel_calls ec
      JOIN allo_analytics.call_analyses ca ON ca.call_id=ec.call_id
      WHERE RIGHT(ec.exotel_number,10) IN ('{nums_csv}') AND ec.routed_to='lead_to_call'
        AND (ec.start_time + {IST})>='{wstart}' AND (ec.start_time + {IST})<'{E}') WHERE rn=1"""

today = datetime.date.today()
mon = today - datetime.timedelta(days=today.weekday())
start = mon - datetime.timedelta(days=7); end = start + datetime.timedelta(days=7)
DAYS = [(start+datetime.timedelta(days=i)).isoformat() for i in range(7)]
S, E = start.isoformat(), end.isoformat()
REC_S = (start - datetime.timedelta(days=35)).isoformat()  # recording lookback (catch older-lead calls)

# 6-way appointment-status map (verified: RESCHEDULED/COMPLETED/MISSED/CANCELLED; SCHEDULED/RECONSULTED future-proofed)
ST_SQL = """CASE
  WHEN a.status IN ('COMPLETED','RECONSULTED') THEN 'done'
  WHEN a.status='SCHEDULED' THEN 'sched'
  WHEN a.status='MISSED' THEN 'noshow'
  WHEN a.status='RESCHEDULED' THEN 'resched'
  WHEN a.status='CANCELLED' THEN 'cancelled'
  ELSE 'other' END"""

out = {"_meta":{"days":DAYS, "week":f"{S}→{(end-datetime.timedelta(days=1)).isoformat()}",
        "note":"① SC bookings = Screening-Call appts scheduled that day at the clinic (all statuses = the clinician calendar). done=COMPLETED/RECONSULTED. age = booking-made − lead-first-seen (exact). src/med from the patient's earliest lead. ② Leads = ALL leads attributed to the clinic by lead.location code, per-lead; connected + intent (patient_intent_strength: STRONG/NOT_A_PATIENT/COULD_NOT_DETERMINE) + care-type (user_intent: therapist/doctor/tests/meds) + recording come from the representative call on the clinic's own lines (lead_to_call). ①source & ②source use different attribution (patient's earliest lead vs clinic code) so they won't perfectly reconcile."},
       "clinics":{}}

for c in CLINICS:
    # ---- A) per-booking rows (+ call recording matched on patient primary OR alternate number) ----
    nums0 = "','".join(c["nums"])
    a = q(f"""
    WITH lead1 AS (SELECT RIGHT(phone_no,10) ph, MIN(created_at) lead_dt FROM allo_persons.lead WHERE deleted_at IS NULL GROUP BY 1),
    cpat AS (SELECT DISTINCT RIGHT(phone_no,10) ph FROM allo_persons.lead WHERE location='{c['code']}' AND deleted_at IS NULL),
    rec AS ({REC_LISTAGG(nums0, REC_S)}),
    metaB AS ({META_BYPHONE(nums0, REC_S)})
    SELECT DATE(a.start_time + {IST}) d,
      p.phone_no phone, p.id pid, COALESCE(pr.name,'Unassigned') doc,
      DATEDIFF(day, DATE(l.lead_dt + {IST}), DATE(a.created_at + {IST})) age,
      TO_CHAR(DATE(a.created_at + {IST}),'YYYY-MM-DD') bkmade,
      {SRC('ld')} src, {MED('ld')} med, {ST_SQL} st,
      REPLACE(REPLACE(REPLACE(COALESCE(a.reason,''),CHR(9),' '),CHR(10),' '),CHR(13),' ') reason,
      CASE WHEN a.program='mental_health' THEN 'MENTAL_HEALTH' WHEN a.program='sexual_health' THEN 'SEXUAL_HEALTH_GENERAL' ELSE '' END cat,
      COALESCE(cbp.summ, cba.summ, '') summ,
      CASE WHEN a.mode='offline' THEN 'offline' ELSE 'online' END booking_mode,
      COALESCE(rp.recs,'') recs_p, COALESCE(ra.recs,'') recs_a
    FROM allo_consultations.appointments a
    JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
    JOIN allo_persons.patient p ON p.id=a.patient_id
    LEFT JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.deleted_at IS NULL
    LEFT JOIN cpat cp ON cp.ph=RIGHT(p.phone_no,10)
    LEFT JOIN allo_persons.providers pr ON pr.id=a.provider_id
    LEFT JOIN lead1 l ON l.ph=RIGHT(p.phone_no,10)
    LEFT JOIN allo_persons.lead ld ON RIGHT(ld.phone_no,10)=l.ph AND ld.created_at=l.lead_dt AND ld.deleted_at IS NULL
    LEFT JOIN rec rp ON rp.ph=RIGHT(p.phone_no,10)
    LEFT JOIN rec ra ON ra.ph=RIGHT(p.alternate_phone_no,10)
    LEFT JOIN metaB cbp ON cbp.ph=RIGHT(p.phone_no,10)
    LEFT JOIN metaB cba ON cba.ph=RIGHT(p.alternate_phone_no,10)
    WHERE a.deleted_at IS NULL AND (a.start_time + {IST})>='{S}' AND (a.start_time + {IST})<'{E}'
      AND ( (loc.locality='{c['loc']}' AND loc.city='{c['city']}')
            OR (a.mode<>'offline' AND cp.ph IS NOT NULL) )
    """)
    days = {d:{"bookings":[], "leads":[]} for d in DAYS}
    docs=set()
    for r in a:
        d=r[0]
        if d not in days: continue
        age = None if (r[4] in NUL) else int(float(r[4]))
        doc=r[3] or "Unassigned"; docs.add(doc)
        days[d]["bookings"].append({"p":r[1], "pid":(r[2] or ""), "doc":doc, "age":age, "bkmade":(g(r,5) or ""),
                                    "src":(g(r,6) or "Direct/unknown"), "med":(g(r,7) or "Web"), "st":r[8],
                                    "rzntxt":(g(r,9) or ""), "rzn":rzn_bucket(g(r,9)),
                                    "cat":(g(r,10) or ""), "summ":(g(r,11) or ""), "mode":(g(r,12) or "offline"),
                                    "recs":parse_recs(g(r,13), g(r,14))})
    # ---- B) per-lead rows (all sources by clinic code) + call outcome/recording + booked flag ----
    nums = "','".join(c["nums"])
    b = q(f"""
    WITH scbk AS (
      SELECT RIGHT(p.phone_no,10) ph, MIN(DATE(a.start_time + {IST})) sc_date
      FROM allo_consultations.appointments a
      JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
      JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.locality='{c['loc']}' AND loc.city='{c['city']}'
      JOIN allo_persons.patient p ON p.id=a.patient_id
      WHERE a.deleted_at IS NULL AND (a.start_time + {IST})>='{S}' AND (a.start_time + {IST})<'{E}'
      GROUP BY 1),
    callout AS (SELECT ph, d, conn, strength, intent FROM (
      SELECT RIGHT(ec."from",10) ph, DATE(ec.start_time + {IST}) d,
        CASE WHEN ec.status='completed' THEN 1 ELSE 0 END conn,
        ca.analysis.patient_intent_strength.result::varchar strength,
        ca.analysis.user_intent.result::varchar intent,
        ROW_NUMBER() OVER (PARTITION BY RIGHT(ec."from",10), DATE(ec.start_time + {IST})
          ORDER BY (CASE WHEN ec.status='completed' THEN 1 ELSE 0 END) DESC, ec.total_duration DESC NULLS LAST) rn
      FROM allo_vendors.exotel_calls ec
      LEFT JOIN allo_analytics.call_analyses ca ON ca.call_id=ec.call_id
      WHERE RIGHT(ec.exotel_number,10) IN ('{nums}') AND ec.routed_to='lead_to_call'
        AND (ec.start_time + {IST})>='{S}' AND (ec.start_time + {IST})<'{E}') WHERE rn=1),
    recL AS ({REC_LISTAGG(nums, S)}),
    metaL AS ({META_BYPHONE(nums, S)}),
    pat AS (SELECT RIGHT(phone_no,10) ph, MAX(id::varchar) pid FROM allo_persons.patient WHERE deleted_at IS NULL GROUP BY 1)
    SELECT DATE(ld.created_at + {IST}) d, ld.phone_no phone, {SRC('ld')} src, {MED('ld')} med,
      COALESCE(co.conn,0) conn, COALESCE(co.strength,'') strength, COALESCE(co.intent,'') intent,
      CASE WHEN sb.ph IS NOT NULL THEN 1 ELSE 0 END booked,
      sb.sc_date bkdate, DATEDIFF(day, DATE(ld.created_at + {IST}), sb.sc_date) blag,
      COALESCE(ml.cat,'') cat, COALESCE(pt.pid,'') pid, COALESCE(ml.summ,'') summ,
      COALESCE(rl.recs,'') recs
    FROM allo_persons.lead ld
    LEFT JOIN callout co ON co.ph=RIGHT(ld.phone_no,10) AND co.d=DATE(ld.created_at + {IST})
    LEFT JOIN scbk sb ON sb.ph=RIGHT(ld.phone_no,10)
    LEFT JOIN recL rl ON rl.ph=RIGHT(ld.phone_no,10)
    LEFT JOIN metaL ml ON ml.ph=RIGHT(ld.phone_no,10)
    LEFT JOIN pat pt ON pt.ph=RIGHT(ld.phone_no,10)
    WHERE ld.deleted_at IS NULL AND ld.location='{c['code']}'
      AND (ld.created_at + {IST})>='{S}' AND (ld.created_at + {IST})<'{E}'
    """)
    for r in b:
        d=r[0]
        if d not in days: continue
        blag = None if g(r,9) in NUL else int(float(r[9]))
        bkdate = "" if g(r,8) in NUL else r[8]
        days[d]["leads"].append({"p":r[1], "src":(r[2] or "Direct/unknown"), "med":(r[3] or "Web"),
                                 "conn":int(r[4]), "strength":(g(r,5) or ""), "intent":(g(r,6) or ""),
                                 "booked":int(r[7]), "bkdate":bkdate, "blag":blag,
                                 "cat":(g(r,10) or ""), "pid":(g(r,11) or ""), "summ":(g(r,12) or ""),
                                 "recs":parse_recs(g(r,13))})
    # ---- C) doctor SC-roster capacity per day: rostered vs realized (shrinkage) + non-bookable (leave) ----
    av = q(f"""
    WITH abtm AS (SELECT DISTINCT appointment_block_id, COALESCE(offline_location_id,online_location_id) blid FROM allo_consultations.appointment_block_type_maps WHERE deleted_at IS NULL)
    SELECT CAST(DATEADD(minute,330,rs.start_time) AS DATE) dt,
      COUNT(*) open_slots,
      SUM(CASE WHEN rs.is_realized=1 THEN 1 ELSE 0 END) realized_slots,
      SUM(CASE WHEN rs.is_realized=1 THEN DATEDIFF(minute,rs.start_time,rs.end_time) ELSE 0 END) realized_mins,
      SUM(CASE WHEN rs.is_realized=1 AND rs.is_booked=1 THEN 1 ELSE 0 END) booked_slots,
      SUM(CASE WHEN rs.is_realized=1 AND rs.available_for_booking=1 AND rs.is_booked=0 AND rs.overlaps_non_bookable_block=0 THEN 1 ELSE 0 END) openleft_slots,
      SUM(CASE WHEN rs.overlaps_non_bookable_block=1 THEN 1 ELSE 0 END) nonbook_slots,
      COUNT(DISTINCT rs.provider_id) docs
    FROM allo_consultations.roster_slots rs
    JOIN abtm ON abtm.appointment_block_id=rs.block_id AND abtm.blid=rs.location_id
    JOIN allo_health.locations l ON l.id=abtm.blid AND l.locality='{c['loc']}' AND l.city='{c['city']}'
    WHERE rs.type_id={SC_TYPE}
      AND DATEADD(minute,330,rs.start_time)>='{S}' AND DATEADD(minute,330,rs.start_time)<'{E}'
    GROUP BY 1""")
    for d in DAYS: days[d]["avail"]=None
    for r in av:
        d=r[0]
        if d not in days: continue
        days[d]["avail"]={"open":int(float(r[1])),"realized":int(float(r[2])),"rhrs":round(float(r[3])/60,1),
                          "booked":int(float(r[4])),"openleft":int(float(r[5])),"nonbook":int(float(r[6])),"docs":int(float(r[7]))}
    out["clinics"][c["key"]]={"disp":c["disp"],"city":c["city"],"loc":c["loc"],
                              "doctors":sorted(docs),"days":days}
    tot=sum(len(days[d]["bookings"]) for d in DAYS)
    done=sum(1 for d in DAYS for bk in days[d]["bookings"] if bk["st"]=="done")
    sd=sum(1 for d in DAYS for bk in days[d]["bookings"] if bk["age"]==0)
    ld=sum(len(days[d]["leads"]) for d in DAYS)
    print(f"{c['key']:<11} {out['_meta']['week']}: {tot} SC bookings ({done} done, {sd} same-day-lead) · {ld} leads · docs={sorted(docs)}")

json.dump(out, open(os.path.join(ROOT,"data_sc_calendar.json"),"w"), separators=(",",":"))
print("wrote data_sc_calendar.json")
