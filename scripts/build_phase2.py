#!/usr/bin/env python3
"""Build Phase-2 datasets for the Clinic Scorecard:
  data_reminders.json : per clinic/week WhatsApp appointment-reminder funnel (sent/delivered/read),
                        with a no-show-specific split. 12 Monday-weeks, newest-first. RELIABLE/deep.
  data_sarvam.json    : NETWORK + by-city snapshot of Sarvam inbound-call quality (did_we_do_it,
                        intent, drop-off). Recent ~2-week snapshot only; clearly flagged in the UI.
Run: python3 scripts/build_phase2.py   (AWS SSO; cluster 'warehouse')"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT,"scripts","redshift_query.py")
WEEKS = ["2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20",
         "2026-04-13","2026-04-06","2026-03-30","2026-03-23","2026-03-16","2026-03-09"]
WI = {w:i for i,w in enumerate(WEEKS)}

def q(f):
    sql = open(os.path.join(ROOT,"scripts",f)).read()
    p = subprocess.run([sys.executable,RUNNER], input=sql, capture_output=True, text=True)
    if p.returncode!=0 or "ERROR" in (p.stderr or ""): sys.exit(f"{f} failed: {(p.stderr or '')[:300]}")
    return [ln.split("\t") for ln in p.stdout.strip("\n").splitlines() if ln.strip()]
def num(x):
    try: return int(float(x))
    except (ValueError,TypeError): return 0

def build_reminders():
    D = {}
    FIELDS = ["total","rem_sent","rem_delivered","rem_read","ns_total","ns_sent","ns_delivered","ns_read"]
    for c in q("fetch_reminders.sql"):
        if len(c) < 11: continue
        city,clinic,wk = c[0],c[1],c[2]
        if wk not in WI: continue
        o = D.setdefault(f"{city}|{clinic}", {f:[0]*12 for f in FIELDS})
        for j,f in enumerate(FIELDS): o[f][WI[wk]] = num(c[3+j])
    out = {"_meta":{"weeks":WEEKS,
        "source":"allo_vendors.whatsapp (reference_entity=appointment, template ILIKE %reminder%) joined to Screening-Call appointments",
        "note":"rem_* = appointments with a reminder sent/delivered/read; ns_* = same restricted to no-shows (missed)"}}
    out.update(D)
    json.dump(out, open(os.path.join(ROOT,"data_reminders.json"),"w"), separators=(",",":"))
    print(f"data_reminders.json · {len(D)} clinics")
    b = D.get("Bangalore|Bellandur")
    if b: print("  Bellandur wk0 — total",b["total"][0],"rem_sent",b["rem_sent"][0],"delivered",b["rem_delivered"][0],
                 "| no-shows",b["ns_total"][0],"got reminder",b["ns_sent"][0],"delivered",b["ns_delivered"][0])
    return D

def build_sarvam():
    net = {"ddwi":{}, "intent":{}, "dropped":{}, "total":0, "our":0}
    bycity = {}
    for c in q("fetch_sarvam.sql"):
        if len(c) < 6: continue
        city,is_our,ddwi,intent,dropped,n = c[0],(c[1] or "").lower()=="true",c[2] or "?",c[3] or "?",c[4] or "?",num(c[5])
        net["total"] += n
        net["ddwi"][ddwi] = net["ddwi"].get(ddwi,0)+n
        net["intent"][intent] = net["intent"].get(intent,0)+n
        net["dropped"][dropped] = net["dropped"].get(dropped,0)+n
        if is_our and city:
            net["our"] += n
            cc = bycity.setdefault(city, {"YES":0,"PARTIALLY":0,"NO":0,"other":0,"total":0})
            cc["total"] += n
            cc[ddwi if ddwi in cc else "other"] = cc.get(ddwi if ddwi in cc else "other",0)+n
    out = {"_meta":{"source":"allo_analytics.call_analyses (Sarvam analysis SUPER)",
        "note":"Recent ~2-week network snapshot of analyzed INBOUND calls. Not per-clinic-week; call->appointment link is sparse. did_we_do_it = agent accomplished the booking goal.",
        "window":"created_at >= 2026-05-25"},
        "network":net, "by_city":bycity}
    json.dump(out, open(os.path.join(ROOT,"data_sarvam.json"),"w"), separators=(",",":"))
    d=net["ddwi"]; tot=net["total"] or 1
    print(f"data_sarvam.json · {net['total']} calls · YES {d.get('YES',0)} ({round(d.get('YES',0)/tot*100)}%) "
          f"PARTIALLY {d.get('PARTIALLY',0)} NO {d.get('NO',0)} · {len(bycity)} our-cities")

def build_conversion():
    D = {}
    FIELDS = ["completed_sc","converted"]
    for c in q("fetch_conversion.sql"):
        if len(c) < 5: continue
        city,clinic,wk = c[0],c[1],c[2]
        if wk not in WI: continue
        o = D.setdefault(f"{city}|{clinic}", {f:[0]*12 for f in FIELDS})
        o["completed_sc"][WI[wk]] = num(c[3]); o["converted"][WI[wk]] = num(c[4])
    # right-censoring: weeks whose 30-day window hasn't fully elapsed as of the data date (2026-06-06)
    # weeks[0..3] (May 25, 18, 11, 04) are within 30 days of 06-06 -> partially censored
    out = {"_meta":{"weeks":WEEKS,
        "source":"allo_consultations.appointments — completed Screening Call -> Follow Up/Therapy within 30 days",
        "note":"converted = completed-SC patients who booked Follow Up/Therapy within 30d. Recent weeks are right-censored (30d window not fully elapsed); flagged in UI.",
        "censored_weeks":4}}
    out.update(D)
    json.dump(out, open(os.path.join(ROOT,"data_conversion.json"),"w"), separators=(",",":"))
    tot_sc=sum(v["completed_sc"][4] for v in D.values()); tot_cv=sum(v["converted"][4] for v in D.values())
    print(f"data_conversion.json · {len(D)} clinics · wk4(uncensored) network {tot_cv}/{tot_sc} = {round(tot_cv/tot_sc*100) if tot_sc else 0}% SC->treatment")

def build_doctor():
    D = {}
    FIELDS = ["sched","shrunk","avail","total","done","missed"]
    for c in q("fetch_doctor.sql"):
        if len(c) < 10: continue
        city,clinic,doctor,wk = c[0],c[1],c[2],c[3]
        if wk not in WI: continue
        o = D.setdefault(f"{city}|{clinic}", {}).setdefault(doctor, {f:[0]*12 for f in FIELDS})
        for j,f in enumerate(FIELDS): o[f][WI[wk]] = num(c[4+j])
    out = {"_meta":{"weeks":WEEKS,
        "source":"allo_consultations.roster_slots + appointments, per provider (allo_persons.providers.name)",
        "note":"per clinic/doctor weekly: sched/shrunk/avail slots + total/done/missed SC appointments. Roster from 2026-04-13."}}
    out.update(D)
    json.dump(out, open(os.path.join(ROOT,"data_doctor.json"),"w"), separators=(",",":"))
    nd=sum(len(v) for v in D.values())
    print(f"data_doctor.json · {len(D)} clinics · {nd} clinic-doctors")
    b=D.get("Bangalore|Indiranagar")
    if b:
        for dn,dv in list(b.items())[:4]: print(f"  Indiranagar · {dn}: sched {dv['sched'][0]} avail {dv['avail'][0]} done {dv['done'][0]} missed {dv['missed'][0]}")

def build_status_who():
    # data_status_who.json: per clinic/week, status counts split by new/fu (and total derived)
    D = {}
    SUB = ["total","done","missed","resched_patient","resched_noshow"]
    for c in q("fetch_status_who.sql"):
        if len(c) < 9: continue
        city,clinic,wk,who = c[0],c[1],c[2],c[3]
        if wk not in WI: continue
        o = D.setdefault(f"{city}|{clinic}", {seg:{f:[0]*12 for f in SUB} for seg in ("new","fu")})
        seg = o.get(who)
        if seg is None: continue
        for j,f in enumerate(SUB): seg[f][WI[wk]] = num(c[4+j])
    out = {"_meta":{"weeks":WEEKS,
        "source":"allo_consultations.appointments — status split by new(first-ever SC) vs follow-up",
        "note":"per clinic/week: for new and fu segments — total/done/missed/resched_patient/resched_noshow. cancelled/scheduled = total - others."}}
    out.update(D)
    json.dump(out, open(os.path.join(ROOT,"data_status_who.json"),"w"), separators=(",",":"))
    b=D.get("Bangalore|Bellandur")
    if b:
        n,fu=b["new"],b["fu"]
        print(f"data_status_who.json · {len(D)} clinics")
        print(f"  Bellandur wk0 — NEW: total {n['total'][0]} done {n['done'][0]} missed {n['missed'][0]} rp {n['resched_patient'][0]}")
        print(f"  Bellandur wk0 — FU : total {fu['total'][0]} done {fu['done'][0]} missed {fu['missed'][0]} rp {fu['resched_patient'][0]}")

if __name__ == "__main__":
    build_reminders()
    build_sarvam()
    build_conversion()
    build_doctor()
    build_status_who()
