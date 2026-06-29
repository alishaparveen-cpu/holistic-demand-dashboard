#!/usr/bin/env python3
"""Build data_scorecard.json — the founder's clinic-scorecard data:
  disp     : per clinic/week dispositions incl reschedule split (patient vs no-show) + recovery
  leadage  : new bookings by fine lead-age bucket (same/lastwk/2-4wk/1-3mo/3+mo)
  channel  : bookings by source channel (C2B numerator; leads denom from data_leads.json)
  dow      : day-of-week booked/done/missed (last ~8 wks) to spot a consistent no-show day
Arrays newest-first aligned to the diagnostic's 12 Monday-weeks. Run: python3 scripts/build_scorecard.py (AWS SSO)"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT,"scripts","redshift_query.py")
WEEKS=["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]
WI = {w:i for i,w in enumerate(WEEKS)}
DOW = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat']

def q(f):
    sql = open(os.path.join(ROOT,"scripts",f)).read()
    p = subprocess.run([sys.executable,RUNNER], input=sql, capture_output=True, text=True)
    if p.returncode!=0 or "ERROR" in p.stderr: sys.exit(f"{f} failed: {(p.stderr or '')[:300]}")
    return [ln.split("\t") for ln in p.stdout.strip("\n").splitlines() if ln.strip()]
def num(x):
    try: return int(float(x))
    except (ValueError,TypeError): return 0

def main():
    D = {}
    def clin(k): return D.setdefault(k, {})
    # ── dispositions ──
    DFIELDS = ["total","new_bk","followup_bk","done","done_new","done_followup","missed","resched_noshow","resched_clinic","resched_patient","recovered_done","cancelled","scheduled"]
    for c in q("fetch_scorecard.sql"):
        if len(c) < 16: continue
        city,clinic,wk = c[0],c[1],c[2]
        if wk not in WI: continue
        o = clin(f"{city}|{clinic}").setdefault("disp", {f:[0]*len(WEEKS) for f in DFIELDS})
        for j,f in enumerate(DFIELDS): o[f][WI[wk]] = num(c[3+j])
    # ── fine lead age ──
    AGES = ["b0_same","b1_lastwk","b2_2to4wk","b3_1to3mo","b4_3moplus"]
    for c in q("fetch_scorecard_leadage.sql"):
        if len(c) < 5: continue
        city,clinic,wk,bucket,n = c[0],c[1],c[2],c[3],num(c[4])
        if wk not in WI or bucket not in AGES: continue
        o = clin(f"{city}|{clinic}").setdefault("leadage", {a:[0]*len(WEEKS) for a in AGES})
        o[bucket][WI[wk]] += n
    # ── bookings by channel ──
    for c in q("fetch_scorecard_channel.sql"):
        if len(c) < 5: continue
        city,clinic,wk,src,n = c[0],c[1],c[2],c[3],num(c[4])
        if wk not in WI: continue
        o = clin(f"{city}|{clinic}").setdefault("channel", {})
        o.setdefault(src, [0]*len(WEEKS))[WI[wk]] += n
    # ── day of week ──
    for c in q("fetch_scorecard_dow.sql"):
        if len(c) < 6: continue
        city,clinic,dow = c[0],c[1],num(c[2])
        o = clin(f"{city}|{clinic}").setdefault("dow", {d:{"booked":0,"done":0,"missed":0} for d in DOW})
        d = DOW[dow]; o[d]["booked"]+=num(c[3]); o[d]["done"]+=num(c[4]); o[d]["missed"]+=num(c[5])
    out = {"_meta":{"weeks":WEEKS, "source":"allo_consultations.appointments (dispositions/dow) + main_source_wise_leads (leadage/channel)",
                    "note":"reschedule split via previous_status; recovery = completed whose prior state was missed; dow last ~8 wks"}}
    out.update(D)
    json.dump(out, open(os.path.join(ROOT,"data_scorecard.json"),"w"), separators=(",",":"))
    print(f"data_scorecard.json · {len(D)} clinics")
    b = D.get("Bangalore|Bellandur")
    if b:
        dp=b.get("disp",{})
        print("Bellandur wk0 — resched: patient", dp.get("resched_patient",[0])[0], "noshow-recycled", dp.get("resched_noshow",[0])[0],
              "· missed", dp.get("missed",[0])[0], "recovered", dp.get("recovered_done",[0])[0])
        print("Bellandur leadage wk0:", {a:b.get("leadage",{}).get(a,[0])[0] for a in AGES})
        print("Bellandur dow:", {d:b["dow"][d] for d in DOW} if "dow" in b else None)

if __name__ == "__main__":
    main()
