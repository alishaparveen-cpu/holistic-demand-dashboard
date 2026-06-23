#!/usr/bin/env python3
"""Network weekly review data → data_weekly_review.json (last 8 ISO weeks, Mon-first, newest-first).

Computes LEADS, BOOKINGS (gross), DONE for each week, sliced by:
  total · channel · city · tier (T1/T2) · category (STI/SH/Other, bookings+done) · online/offline
so weekly-review.html can show week-vs-last-week-vs-6wk-avg across every cut.

Definitions:
  LEADS    = main_source_wise_leads rows by created week, channel=source, city=call_location clinic→city.
             offline = lead tied to a physical clinic; online = no clinic (national/online).
  BOOKINGS = Screening-Call appointments by appointment week, gross = status NOT IN (rescheduled,cancelled).
  DONE     = Screening Calls with status COMPLETED.
  channel(book/done) = the patient's originating lead source. category = consultation diagnosis
             (sti→STI; ed/pe→SH; else Other). online/offline = clinic locality='online' vs physical.
Run: AWS_PROFILE=redshift-data python3 scripts/build_weekly_review.py
"""
import os, sys, subprocess, json, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
# 8 Mondays, newest-first (index0 = current week, may be partial)
WEEKS = ["2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27"]
idx = {w:i for i,w in enumerate(WEEKS)}; NW=len(WEEKS); START="2026-04-27"
T1 = {"Bangalore","Mumbai","Pune","Hyderabad","Chennai"}
CITYNORM = {"Bengaluru":"Bangalore","Hubballi":"Hubli","Mysore":"Mysuru","Mangalore":"Mangaluru","Vizag":"Visakhapatnam"}
def chan_norm(s):
    s=(s or "").strip().lower()
    if s.startswith("google"): return "Google"
    if s.startswith("gmb"): return "GMB"
    if s=="practo": return "Practo"
    if s.startswith("organic"): return "Organic"
    if s in ("fb","facebook","meta","ig","instagram"): return "Meta"
    if s in ("justdial","jd"): return "JustDial"
    return "Other"
DIAG = {"sti":"STI","ed_plus":"SH","pe_plus":"SH","ed_plus_pe_plus":"SH","nssd":"Other"}

LEADS_SQL = """
SELECT TO_CHAR(DATE_TRUNC('week', created_on_date)::date,'YYYY-MM-DD') wk,
       COALESCE(NULLIF(source,''),'Other') src,
       COALESCE(NULLIF(call_location,''),'') loc,
       COUNT(*) n
FROM production.public.main_source_wise_leads
WHERE created_on_date >= '%s'
GROUP BY 1,2,3;""" % START

BOOK_SQL = """
WITH loc AS (SELECT id, MAX(city) city, MAX(locality) locality FROM allo_health.locations WHERE deleted_at IS NULL GROUP BY id),
diag AS (
  SELECT e.appointment_id ap_id,
    CASE WHEN MAX(CASE WHEN et.tag_type='sti' THEN 1 ELSE 0 END)=1 THEN 'sti'
         WHEN MAX(CASE WHEN et.tag_type IN ('ed_plus','pe_plus','ed_plus_pe_plus') THEN 1 ELSE 0 END)=1 THEN 'ed_plus'
         WHEN MAX(CASE WHEN et.tag_type='nssd' THEN 1 ELSE 0 END)=1 THEN 'nssd' ELSE 'oth' END dc
  FROM allo_encounters.encounters e
  LEFT JOIN allo_analytics.encounter_tags et ON et.encounter_id=e.id AND et.tag_category='diagnosis' AND et.deleted_at IS NULL
  WHERE e.deleted_at IS NULL GROUP BY 1),
sc AS (
  SELECT a.id ap_id, a.start_time stt, a.location_id loc_id, a.patient_id pid, LOWER(a.status) st,
    CASE WHEN LAG(a.start_time) OVER (PARTITION BY a.patient_id ORDER BY a.start_time) IS NULL THEN 1 ELSE 0 END is_new
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  WHERE a.deleted_at IS NULL)
SELECT TO_CHAR(DATE_TRUNC('week', sc.stt + INTERVAL '5 hours 30 minutes')::date,'YYYY-MM-DD') wk,
  COALESCE(l2.city,'?') city, COALESCE(l2.locality,'?') locality,
  COALESCE(diag.dc,'oth') dc, sc.st, sc.is_new,
  COALESCE(led.utm_source,'Other') chan, COUNT(*) n
FROM sc
JOIN loc l2 ON l2.id=sc.loc_id
LEFT JOIN diag ON diag.ap_id=sc.ap_id
LEFT JOIN allo_persons.patient p ON p.id=sc.pid
LEFT JOIN allo_persons.lead led ON led.id=p.lead_id
WHERE sc.stt >= '%s'
GROUP BY 1,2,3,4,5,6,7;""" % START

def run(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode!=0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("query failed: "+(p.stderr or "")[:400]+"\n"); sys.exit(1)
    return [ln.split("\t") for ln in p.stdout.strip().splitlines() if ln.strip()]

def Z(): return [0]*NW
def catset(): return {"STI":Z(),"SH":Z(),"Other":Z()}
def blank():  # a metric with all slices
    return {"total":Z(), "channel":{}, "city":{}, "tier":{"T1":Z(),"T2":Z()},
            "online":Z(), "offline":Z(), "cat":catset(),
            "tiercat":{"T1":catset(),"T2":catset()}, "citycat":{}}
def addk(d,key,i,n):
    if key not in d: d[key]=Z()
    d[key][i]+=n

def main():
    loc2city={}
    for k in json.load(open(os.path.join(ROOT,"data_clinic_funnel.json")))["clinics"]:
        cy,lc=k.split("|"); loc2city[lc.strip().lower()]=cy
    def city_of(loc):
        c=loc2city.get((loc or "").strip().lower())
        if c: return CITYNORM.get(c,c)
        c=CITYNORM.get(loc,loc)
        return c if c else "Online / National"

    leads=blank(); books=blank(); dones=blank()

    # ---- LEADS ----
    for r in run(LEADS_SQL):
        if len(r)<4: continue
        wk,src,loc,n=r[0],r[1],r[2],r[3]
        if wk not in idx: continue
        try: n=int(n)
        except ValueError: continue
        i=idx[wk]; ch=chan_norm(src)
        leads["total"][i]+=n; addk(leads["channel"],ch,i,n)
        # offline = tied to a physical clinic locality; online = none
        if loc and loc.strip().lower() not in ("","online","national","practo online"):
            cy=city_of(loc); leads["offline"][i]+=n
            addk(leads["city"],cy,i,n); leads["tier"]["T1" if cy in T1 else "T2"][i]+=n
        else:
            leads["online"][i]+=n

    # ---- BOOKINGS (new = first-ever SC) + DONE (completed) ----
    for r in run(BOOK_SQL):
        if len(r)<8: continue
        wk,city,locality,dc,st,isnew,chan,n=r
        if wk not in idx: continue
        try: n=int(n)
        except ValueError: continue
        i=idx[wk]
        gross = st not in ("rescheduled","cancelled")
        newb  = gross and isnew=="1"        # new booking = patient's first-ever SC
        done  = st=="completed"
        if not newb and not done: continue
        ch=chan_norm(chan); cat=DIAG.get(dc,"Other")
        city_real = city not in ("?","",None)
        online = (locality or "").strip().lower()=="online" or not city_real   # online clinic has null city
        cy = None if online else CITYNORM.get(city, city)
        for M,flag in ((books,newb),(dones,done)):
            if not flag: continue
            M["total"][i]+=n
            addk(M["channel"],ch,i,n); M["cat"][cat][i]+=n
            if online: M["online"][i]+=n
            else:
                tier="T1" if cy in T1 else "T2"
                M["offline"][i]+=n; addk(M["city"],cy,i,n); M["tier"][tier][i]+=n
                M["tiercat"][tier][cat][i]+=n
                if cy not in M["citycat"]: M["citycat"][cy]=catset()
                M["citycat"][cy][cat][i]+=n

    out={"_meta":{"weeks":WEEKS,"t1":sorted(T1),
          "note":"Network weekly review. LEADS=main_source_wise_leads by created week (channel=source; offline=clinic-tied, online=national). BOOKINGS=gross SC (excl reschedule/cancel); DONE=completed SC; by appointment week. category=diagnosis (STI / SH=ED·PE / Other; no MH tag). channel(book/done)=originating lead source. index0 (15 Jun) = current week, may be partial.",
          "gaps":"leads have no clinical category or maturity bucket at network level; online/offline for leads is a clinic-tied proxy."},
        "leads":leads,"bookings":books,"done":dones}
    json.dump(out, open(os.path.join(ROOT,"data_weekly_review.json"),"w"), separators=(",",":"))
    L,B,D=leads["total"],books["total"],dones["total"]
    print("wrote data_weekly_review.json")
    print(f"  weeks(newest→): {WEEKS}")
    print(f"  leads:    {L}")
    print(f"  bookings: {B}")
    print(f"  done:     {D}")
    print(f"  latest complete wk (8-14 Jun): leads {L[1]} book {B[1]} done {D[1]} · cities {len(books['city'])} channels {list(books['channel'])}")

if __name__=="__main__":
    main()
