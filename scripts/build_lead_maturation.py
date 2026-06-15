#!/usr/bin/env python3
"""Build data_lead_maturation.json — per clinic, the lead→booking MATURATION curve for the
Google/GMB/Organic universe (the channels with booking-timing). For leads created in a week
(denominator = total non-Practo inbound leads from data_leads.json), the cumulative % booked by
lag 0 (same week), 1, 2, 3, 4+ weeks. Numerator = cohort bookings by lag from
production.public.main_source_wise_leads. The 4+ value is the mature ceiling.
Practo is excluded (no booking-timing) and tracked separately in the dashboard.
Run: python3 scripts/build_lead_maturation.py   (needs AWS SSO)"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKS=["2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23"]
WSET = set(WEEKS)
SETTLED_CUTOFF = "2026-05-04"   # cohort had >=4 full weeks to convert before the 2026-06-01 cutoff
LEAD_SOURCES = ["gmb","google_ad","organic","fb","justdial","others"]   # data_leads non-Practo sources

def main():
    dl = json.load(open(os.path.join(ROOT,"data_leads.json")))
    leadsOf = {}
    for k, v in dl.items():
        if k == "_meta": continue
        leadsOf[k] = {w: sum(int((v.get(s) or [0]*12)[i] or 0) for s in LEAD_SOURCES) for i, w in enumerate(WEEKS)}
    sql = open(os.path.join(ROOT,"scripts","fetch_lead_maturation.sql")).read()
    p = subprocess.run([sys.executable, os.path.join(ROOT,"scripts","redshift_query.py")],
                       input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in p.stderr:
        sys.stderr.write("fetch_lead_maturation.sql failed: "+(p.stderr or "")[:300]+"\n"); sys.exit(1)
    def num(x):
        try: return int(float(x))
        except (ValueError, TypeError): return 0
    acc, net = {}, [0,0,0,0,0,0]
    for line in p.stdout.strip("\n").splitlines():
        c = line.split("\t")
        if len(c) < 8: continue
        city, clinic, cohort = c[0], c[1], c[2]
        if cohort > SETTLED_CUTOFF or cohort not in WSET: continue
        key = f"{city}|{clinic}"
        L = leadsOf.get(key, {}).get(cohort, 0)
        if L <= 0: continue
        bk = [num(c[3]), num(c[4]), num(c[5]), num(c[6]), num(c[7])]
        a = acc.setdefault(key, [0,0,0,0,0,0]); a[0]+=L; net[0]+=L
        for i in range(5): a[i+1]+=bk[i]; net[i+1]+=bk[i]
    def curve(a):
        L = a[0]
        if L <= 0: return None
        cum, out = 0, []
        for i in range(1,6):
            cum += a[i]; out.append(min(100.0, round(cum/L*100, 1)))
        return {"curve": out, "sameWeek": out[0], "mature": out[-1], "leads": L}
    netCurve = curve(net)
    D = {"_meta": {"source":"main_source_wise_leads bookings-by-lag ÷ data_leads non-Practo inbound leads · settled cohorts (<= "+SETTLED_CUTOFF+")",
                   "scope":"Google/GMB/Organic universe (Practo excluded — no booking-timing)",
                   "lags":"cumulative % booked by lag 0(same wk)/1/2/3/4+ weeks", "network": netCurve}}
    n = 0
    for key, a in acc.items():
        cv = curve(a)
        if cv and cv["leads"] >= 25: D[key] = cv; n += 1
    json.dump(D, open(os.path.join(ROOT,"data_lead_maturation.json"),"w"), separators=(",",":"))
    print(f"data_lead_maturation.json · {n} clinics · network {netCurve['curve'] if netCurve else None}")
    b = D.get("Bangalore|Bellandur")
    if b: print("Bellandur:", b["curve"], "· same-wk", b["sameWeek"], "→ mature", b["mature"])

if __name__ == "__main__":
    main()
