#!/usr/bin/env python3
"""Build data_demand_funnel.json — the qualified-lead funnel per clinic/week from
production.public.demand_data_week_superset (maintained weekly; relevant = inbound-call relevance
flag set by agents / Sarvam AI). Keyed City|Clinic, arrays newest-first aligned to the diagnostic's
12 Monday-weeks. Splits out GMB+Google and Practo by final_source.
Run: python3 scripts/build_demand_superset.py   (needs AWS SSO)"""
import os, sys, subprocess, json, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKS=["2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23","2026-03-16"]
idx = {w:i for i,w in enumerate(WEEKS)}
def monday_from_ending(wk_end):                      # week column is Sunday (week-ending) → Monday = -6 days
    y,m,d = map(int, wk_end.split("-")); return (datetime.date(y,m,d) - datetime.timedelta(days=6)).isoformat()
GMB_GOOGLE = {"gmb","google","gmb+google","google listing","pc-inbound","organic","google ads","google_ad"}
def src_group(s):
    s = (s or "").lower()
    if "practo" in s: return "practo"
    if any(k in s for k in ("gmb","google","organic","listing","pc-inbound","ads")): return "gmb_google"
    return "other"
FIELDS = ["leads","relevant","booked","sw_booked","pw_booked","new_booked","calls_done","a1","a2","a3","a3plus"]

def main():
    sql = open(os.path.join(ROOT,"scripts","fetch_demand_superset.sql")).read()
    p = subprocess.run([sys.executable, os.path.join(ROOT,"scripts","redshift_query.py")],
                       input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in p.stderr:
        sys.stderr.write("fetch_demand_superset.sql failed: "+(p.stderr or "")[:300]+"\n"); sys.exit(1)
    def blank(): return {f:[0]*12 for f in FIELDS}
    def num(x):
        try: return int(float(x))
        except (ValueError, TypeError): return 0          # null cells come through as "True"/"" → 0
    D = {}
    for line in p.stdout.strip("\n").splitlines():
        c = line.split("\t")
        if len(c) < 15: continue
        city, loc, wk_end, src = c[0], c[1], c[2], c[3]
        wk = monday_from_ending(wk_end)
        if wk not in idx: continue
        i = idx[wk]; key = f"{city}|{loc}"; g = src_group(src)
        vals = {FIELDS[k]: num(c[4+k]) for k in range(len(FIELDS))}
        o = D.setdefault(key, {"all":blank(), "gmb_google":blank(), "practo":blank()})
        for f in FIELDS:
            o["all"][f][i] += vals[f]
            if g in ("gmb_google","practo"): o[g][f][i] += vals[f]
    out = {"_meta":{"source":"production.public.demand_data_week_superset (maintained weekly)",
                    "weeks":WEEKS, "relevant":"inbound-call relevance flag (agents / Sarvam AI)",
                    "fields":"leads·relevant·booked·sw_booked(this-wk lead)·pw_booked(last-wk lead)·new_booked·calls_done·a1/a2/a3/a3plus(call attempts)"}}
    out.update(D)
    json.dump(out, open(os.path.join(ROOT,"data_demand_funnel.json"),"w"), separators=(",",":"))
    print(f"data_demand_funnel.json · {len(D)} clinics")
    b = D.get("Bangalore|Bellandur")
    if b: print("Bellandur wk0 — leads:", b["all"]["leads"][0], "relevant:", b["all"]["relevant"][0],
                "booked:", b["all"]["booked"][0], "practo booked:", b["practo"]["booked"][0])

if __name__ == "__main__":
    main()
