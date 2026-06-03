#!/usr/bin/env python3
"""
build_channel_data.py — Aggregate /tmp/bookings_full.csv into
clinic/city x week x channel x category (Calls Done), the SAME way rebuild_data.py
builds weekly_clinic — just with an added channel dimension.

Because it uses the identical CSV + COMPLETED/schedule-week/category logic,
summing over channels must equal data.json's weekly_clinic categories EXACTLY.

Run after: AWS_PROFILE=redshift-data python3 fetch_bookings.py
Output:    data_channel.json   +   prints a reconciliation report vs data.json
"""
import csv, json, os
from collections import defaultdict
from datetime import datetime, timedelta, date

CSV_PATH = "/tmp/bookings_full.csv"
ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT      = os.path.join(ROOT, "data_channel.json")
CATS     = ["STI", "ED+", "PE+", "ED+PE+", "NSSD", "MH", "oth"]
CHANNELS = ["GMB", "Google", "Practo", "Organic", "Meta", "Others"]

def map_channel(src):
    s = (src or "").strip().lower()
    if s.startswith("gmb"): return "GMB"
    if s.startswith("google"): return "Google"
    if s == "practo": return "Practo"
    if s.startswith("organic"): return "Organic"
    if s in ("fb","ig","instagram","meta") or s.startswith("fb "): return "Meta"
    return "Others"

def map_cat(raw):
    c = (raw or "").strip()
    return c if c in CATS else "oth"

def week_start_monday(d): return d - timedelta(days=d.weekday())

def detail():
    d = {c:0 for c in CATS}; d["total"]=0; return d

def main():
    data = json.load(open(os.path.join(ROOT,"data.json")))
    weeks = data["weeks"]; wset = set(weeks)
    off = data["offline"]

    # clinic[key][week][channel] -> {cats,total}; city[city][week][channel]; net[week][channel]
    clinic = defaultdict(lambda: defaultdict(lambda: defaultdict(detail)))
    city   = defaultdict(lambda: defaultdict(lambda: defaultdict(detail)))
    netall = defaultdict(lambda: defaultdict(detail))   # all-scope channel (vs weekly_channel)

    n=0
    for row in csv.DictReader(open(CSV_PATH)):
        if row["apt_status_final"].strip() != "COMPLETED": continue
        sched = row["apt_schedule_dt"].strip()
        if not sched: continue
        try: wk = week_start_monday(datetime.strptime(sched,"%Y-%m-%d").date()).isoformat()
        except ValueError: continue
        if wk not in wset: continue
        ch  = map_channel(row["Source final"]); cat = map_cat(row["diag_cat"])
        cty = row["city"].strip(); loc = row["locality"].strip()
        offline = bool(cty) and loc.lower() != "online"
        # network all-scope channel (compare to data.json weekly_channel which is all-scope per-channel cat)
        d0=netall[wk][ch]; d0[cat]+=1; d0["total"]+=1
        if not offline: continue          # drill-down is offline geo
        n+=1
        key = f"{cty}_{loc}" if cty else f"_{loc}"
        d1=clinic[key][wk][ch]; d1[cat]+=1; d1["total"]+=1
        if cty:
            d2=city[cty][wk][ch]; d2[cat]+=1; d2["total"]+=1

    # ── write output ──
    out = {
        "generated_at": datetime.utcnow().isoformat()+"Z",
        "weeks": weeks, "channels": CHANNELS, "cats": CATS,
        "offline": {
            "clinic": {k:{w:dict(clinic[k][w]) for w in clinic[k]} for k in clinic},
            "city":   {c:{w:dict(city[c][w])   for w in city[c]}   for c in city},
        },
    }
    json.dump(out, open(OUT,"w"))
    print(f"✓ wrote {OUT}  ({n:,} offline COMPLETED rows · {len(clinic)} clinics · {len(city)} cities)")

    # ── VERIFY 1: sum over channels of clinic×cat == data.json weekly_clinic (should be EXACT) ──
    print("\n=== VERIFY 1 — clinic×channel summed over channels  vs  data.json weekly_clinic (offline) ===")
    exact=mism=0; worst=[]
    for w in weeks:
        wc = off["weekly_clinic"].get(w,{})
        for key,rec in wc.items():
            got = defaultdict(int)
            for ch in clinic.get(key,{}).get(w,{}).values():
                for c in CATS: got[c]+=ch[c]
            for c in CATS:
                e=rec.get(c,0); g=got[c]
                if e==g: exact+=1
                else:
                    mism+=1
                    if abs(e-g)>0: worst.append((abs(e-g),w,key,c,e,g))
    tot=exact+mism
    print(f"  cells exact: {exact}/{tot}  ({exact/tot*100:.1f}%)   mismatches: {mism}")
    worst.sort(reverse=True)
    for d,w,k,c,e,g in worst[:8]: print(f"    Δ{d}  {w} {k} {c}: data.json={e} channel-split={g}")

    # ── VERIFY 2: network channel totals vs data.json weekly_channel (latest 3 weeks) ──
    print("\n=== VERIFY 2 — network channel totals  vs  data.json weekly_channel (all-scope) ===")
    wch = off["weekly_channel"]  # offline weekly_channel
    allch = data["all"]["weekly_channel"]
    for w in weeks[-3:]:
        print(f"  {w}:")
        for ch in CHANNELS:
            mine = netall[w][ch]["total"]
            ref  = allch.get(w,{}).get(ch,{}).get("total",0)
            mark = "✓" if (ref==0 and mine==0) or (ref and abs(mine-ref)/ref<=0.05) else "≈" if ref and abs(mine-ref)/max(ref,1)<=0.15 else "✗"
            print(f"    {ch:8} channel-split={mine:4}   weekly_channel(all)={ref:4}   {mark}")

if __name__=="__main__":
    main()
