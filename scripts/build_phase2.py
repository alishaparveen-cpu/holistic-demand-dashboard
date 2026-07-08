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
WEEKS=["2026-07-06","2026-06-29","2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]
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
        o = D.setdefault(f"{city}|{clinic}", {f:[0]*len(WEEKS) for f in FIELDS})
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
        "window":"created_at >= 2026-06-01"},
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
        o = D.setdefault(f"{city}|{clinic}", {f:[0]*len(WEEKS) for f in FIELDS})
        o["completed_sc"][WI[wk]] = num(c[3]); o["converted"][WI[wk]] = num(c[4])
    # right-censoring: weeks whose 30-day window hasn't fully elapsed as of the data date (2026-06-13)
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
        o = D.setdefault(f"{city}|{clinic}", {}).setdefault(doctor, {f:[0]*len(WEEKS) for f in FIELDS})
        for j,f in enumerate(FIELDS): o[f][WI[wk]] = num(c[4+j])
    out = {"_meta":{"weeks":WEEKS,
        "source":"allo_consultations.roster_slots + appointments, per provider (allo_persons.providers.name)",
        "note":"per clinic/doctor weekly: sched/shrunk/avail slots + total/done/missed SC appointments. Roster from 2026-04-20."}}
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
    SUB = ["total","done","missed","resched_patient","resched_clinic","resched_noshow","cancelled","scheduled"]
    for c in q("fetch_status_who.sql"):
        if len(c) < 12: continue
        city,clinic,wk,who = c[0],c[1],c[2],c[3]
        if wk not in WI: continue
        o = D.setdefault(f"{city}|{clinic}", {seg:{f:[0]*len(WEEKS) for f in SUB} for seg in ("new","rebook","return")})
        seg = o.get(who)
        if seg is None: continue
        for j,f in enumerate(SUB): seg[f][WI[wk]] = num(c[4+j])
    out = {"_meta":{"weeks":WEEKS,
        "source":"allo_consultations.appointments — status split by new(first-ever SC) / rebook(reschedule/re-book <14d) / return(genuine repeat 14d+)",
        "note":"per clinic/week: for new/rebook/return segments — total/done/missed/resched_*. cancelled/scheduled = total - others."}}
    out.update(D)
    json.dump(out, open(os.path.join(ROOT,"data_status_who.json"),"w"), separators=(",",":"))
    b=D.get("Bangalore|Bellandur")
    if b:
        print(f"data_status_who.json · {len(D)} clinics")
        for s in ("new","rebook","return"):
            seg=b.get(s,{}); print(f"  Bellandur wk0 — {s.upper()}: total {seg.get('total',[0])[0]}")

def build_retention():
    D = {}
    FIELDS = ["cohort","d0","d1","d2","d3plus","total_tx"]
    for c in q("fetch_retention.sql"):
        if len(c) < 9: continue
        city,clinic,wk = c[0],c[1],c[2]
        if wk not in WI: continue
        o = D.setdefault(f"{city}|{clinic}", {f:[0]*len(WEEKS) for f in FIELDS})
        for j,f in enumerate(FIELDS): o[f][WI[wk]] = num(c[3+j])
    out = {"_meta":{"weeks":WEEKS,
        "source":"allo_consultations.appointments — completed SC cohort → completed Follow Up/Therapy within 60 days",
        "note":"retained = cohort patients with >=1 treatment visit in 60d. Recent ~9 weeks right-censored (60d window); flagged in UI.",
        "censored_weeks":9}}
    out.update(D)
    json.dump(out, open(os.path.join(ROOT,"data_retention.json"),"w"), separators=(",",":"))
    # mature week 9 (index 9 = ~10 wks ago, fully elapsed)
    mi=9; tc=sum(v["cohort"][mi] for v in D.values()); tr=sum(v["cohort"][mi]-v["d0"][mi] for v in D.values())
    print(f"data_retention.json · {len(D)} clinics · wk{mi} network retained {tr}/{tc} = {round(tr/tc*100) if tc else 0}%")

def build_callback():
    D = {}
    FIELDS = ["noshows","called_back"]
    for c in q("fetch_callback.sql"):
        if len(c) < 5: continue
        city,clinic,wk = c[0],c[1],c[2]
        if wk not in WI: continue
        o = D.setdefault(f"{city}|{clinic}", {f:[0]*len(WEEKS) for f in FIELDS})
        o["noshows"][WI[wk]] = num(c[3]); o["called_back"][WI[wk]] = num(c[4])
    out = {"_meta":{"weeks":WEEKS,
        "source":"allo_consultations.appointments (missed) + allo_persons.patient.phone_no joined to allo_vendors.exotel_calls (outbound, within 7d after)",
        "note":"called_back = no-show patients who received an outbound call within 7 days of the missed appointment"}}
    out.update(D)
    json.dump(out, open(os.path.join(ROOT,"data_callback.json"),"w"), separators=(",",":"))
    tn=sum(v["noshows"][0] for v in D.values()); tc=sum(v["called_back"][0] for v in D.values())
    print(f"data_callback.json · {len(D)} clinics · wk0 network called-back {tc}/{tn} = {round(tc/tn*100) if tn else 0}%")

def build_leadage_channel():
    # data_leadage_channel.json: { "City|Clinic": { channel: { bucket: [12] } } } + 'all' channel
    AGES=["b0_same","b1_lastwk","b2_2to4wk","b3_1to3mo","b4_3moplus"]
    D={}
    for c in q("fetch_leadage_channel.sql"):
        if len(c) < 6: continue
        city,clinic,wk,ch,bk,n = c[0],c[1],c[2],c[3],c[4],num(c[5])
        if wk not in WI or bk not in AGES: continue
        key=f"{city}|{clinic}"
        o=D.setdefault(key,{})
        for cc in (ch,'all'):
            seg=o.setdefault(cc,{a:[0]*len(WEEKS) for a in AGES})
            seg[bk][WI[wk]]+=n
    out={"_meta":{"weeks":WEEKS,"source":"main_source_wise_leads — lead-age buckets split by channel","note":"Practo excluded (external feed). 'all' = sum of channels."}}
    out.update(D)
    json.dump(out, open(os.path.join(ROOT,"data_leadage_channel.json"),"w"), separators=(",",":"))
    b=D.get("Bangalore|Bellandur",{})
    print(f"data_leadage_channel.json · {len(D)} clinics · Bellandur channels: {list(b.keys())}")

def build_l2c():
    # data_l2c.json: NETWORK weekly funnel (in/out split) + by-source + by-city + TAT
    NF=["leads","out_reached","out_conn","in_reached","in_conn","any_reached","any_conn","booked","booked_conn"]
    net={f:[0]*len(WEEKS) for f in NF}
    for c in q("fetch_l2c.sql"):
        if len(c) < 10: continue
        if c[0] not in WI: continue
        for j,f in enumerate(NF): net[f][WI[c[0]]]=num(c[1+j])
    by_source=[{"src":c[0],"leads":num(c[1]),"reached":num(c[2]),"connected":num(c[3]),"booked":num(c[4])}
               for c in q("fetch_l2c_source.sql") if len(c)>=5]
    by_city=[{"city":c[0],"leads":num(c[1]),"reached":num(c[2]),"connected":num(c[3]),"booked":num(c[4])}
             for c in q("fetch_l2c_city.sql") if len(c)>=5]
    tat={c[0]:num(c[1]) for c in q("fetch_l2c_tat.sql") if len(c)>=2}
    out={"_meta":{"weeks":WEEKS,"scope":"network","window4":"2026-05-04..2026-06-01",
        "source":"allo_persons.lead + exotel_calls (in & out) + Screening Call appts",
        "note":"reached/connected within 14d (in=lead called us, out=team dialled). booked=phone matched SC within 14d. by_city is a ~9% subset (most leads lack city). by_source over last 4 wks."},
        "net":net, "by_source":by_source, "by_city":by_city, "tat":tat}
    json.dump(out, open(os.path.join(ROOT,"data_l2c.json"),"w"), separators=(",",":"))
    print(f"data_l2c.json · wk0 leads {net['leads'][0]} any_reached {net['any_reached'][0]} any_conn {net['any_conn'][0]} booked {net['booked'][0]} · {len(by_source)} sources · {len(by_city)} cities")

def build_daily():
    # data_daily.json: per clinic, date -> [total,new,done,missed] for the WTD view
    D={}
    for c in q("fetch_daily.sql"):
        if len(c) < 7: continue
        D.setdefault(f"{c[0]}|{c[1]}", {})[c[2]] = [num(c[3]),num(c[4]),num(c[5]),num(c[6])]
    import datetime as _dt
    out={"_meta":{"as_of":"2026-06-13","fields":["total","new","done","missed"],
        "source":"allo_consultations.appointments daily (Screening Call) — WTD vs same-range-last-week"}}
    out.update(D)
    json.dump(out, open(os.path.join(ROOT,"data_daily.json"),"w"), separators=(",",":"))
    print(f"data_daily.json · {len(D)} clinics")

if __name__ == "__main__":
    for fn in (build_reminders, build_sarvam, build_conversion, build_doctor, build_status_who, build_retention, build_callback, build_leadage_channel, build_l2c, build_daily):
        try: fn()
        except SystemExit as e: print(f"  [skip] {fn.__name__}: {e}")
        except Exception as e: print(f"  [skip] {fn.__name__}: {type(e).__name__}: {e}")
