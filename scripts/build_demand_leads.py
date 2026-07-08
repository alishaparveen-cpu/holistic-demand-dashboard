#!/usr/bin/env python3
"""Build data_demand_leads.json — the CORRECT per-clinic leads for the marketing view, from the
demand tracker `production.public.demand_data_week_superset` (the team's maintained weekly demand
superset, current to the latest reported week). This is the source behind the "Bookings & Leads
Trends" sheet — far fuller than build_weekly_diag's main_source_wise_leads(Offline) count.

Keyed by the weekly_diag clinic SLUG, aligned to weekly_diag's Monday-week grid (newest-last, same
as data_weekly_diag). Per slug:
  leads        total lead_count per week
  by_channel   marketing buckets {GMB, Google, Fb, Practo, Organic, Others}  (SRCF match)
  by_src       fine tracker sources {gmb, google, fb, organic_whatsapp, practo, ...}  (breakdown)
marketing-diagnostic.html overlays these onto D.clinics[slug].demand at boot (marketing view only —
city-head untouched). Run: python3 scripts/build_demand_leads.py   (needs AWS SSO; do NOT pause cluster)
"""
import os, sys, subprocess, json, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def bucket(s):
    s = (s or "").lower()
    if s == "gmb": return "GMB"
    if s == "google": return "Google"
    if s in ("fb", "ig", "instagram", "meta"): return "Fb"
    if "practo" in s: return "Practo"
    if s.startswith("organic"): return "Organic"
    return "Others"

BUCKETS = ["GMB", "Google", "Fb", "Practo", "Organic", "Others"]

def main():
    wd = json.load(open(os.path.join(ROOT, "data_weekly_diag.json")))
    WEEKS = wd["weeks"]                       # Monday-based, ascending (newest last)
    N = len(WEEKS); widx = {w: i for i, w in enumerate(WEEKS)}
    # slug ↔ (city, loc)  and a (city,loc)->slug lookup (case-insensitive)
    key2slug = {}
    for slug, c in wd["clinics"].items():
        key2slug[(c["city"].strip().lower(), (c.get("loc") or "").strip().lower())] = slug

    mon_start = datetime.date.fromisoformat(WEEKS[0])                 # earliest Monday
    sun_lo = mon_start + datetime.timedelta(days=6)                   # its week-ending Sunday
    sun_hi = datetime.date.fromisoformat(WEEKS[-1]) + datetime.timedelta(days=6)
    sql = f"""SELECT city, locality, TO_CHAR(week,'YYYY-MM-DD') wk_end,
        COALESCE(final_source,'(none)') fs, SUM(lead_count) leads
      FROM production.public.demand_data_week_superset
      WHERE week >= '{sun_lo.isoformat()}' AND week <= '{sun_hi.isoformat()}'
      GROUP BY 1,2,3,4"""
    p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "redshift_query.py")],
                       input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "FAIL" in p.stderr:
        sys.stderr.write("query failed: " + (p.stderr or "")[:300] + "\n"); sys.exit(1)

    Z = lambda: [0]*N
    def blank(): return {"leads": Z(), "by_channel": {b: Z() for b in BUCKETS}, "by_src": {}}
    acc = {}; unmapped = {}
    unattr = {"leads": Z(), "by_channel": {b: Z() for b in BUCKETS}, "by_src": {}}   # national / online, no clinic
    for line in p.stdout.splitlines():
        f = line.split("\t")
        if len(f) < 5: continue
        city, loc, wk_end, fs, leads = f
        try: n = int(float(leads))
        except (ValueError, TypeError): continue
        if not n: continue
        try: mon = (datetime.date.fromisoformat(wk_end) - datetime.timedelta(days=6)).isoformat()
        except ValueError: continue
        if mon not in widx: continue
        i = widx[mon]
        slug = key2slug.get((city.strip().lower(), (loc or "").strip().lower()))
        if not slug:                                          # no clinic → national / online unattributed
            unmapped[(city, loc)] = unmapped.get((city, loc), 0) + n
            unattr["leads"][i] += n
            unattr["by_channel"][bucket(fs)][i] += n
            unattr["by_src"].setdefault(fs, Z())[i] += n
            continue
        o = acc.setdefault(slug, blank())
        o["leads"][i] += n
        o["by_channel"][bucket(fs)][i] += n
        o["by_src"].setdefault(fs, Z())[i] += n

    for slug, o in acc.items():
        o["by_src"] = {s: a for s, a in o["by_src"].items() if sum(a) > 0}
    unattr["by_src"] = {s: a for s, a in unattr["by_src"].items() if sum(a) > 0}
    unattr["by_channel"] = {b: a for b, a in unattr["by_channel"].items() if sum(a) > 0}

    out = {"_meta": {"source": "demand_data_week_superset (demand tracker) → marketing leads overlay",
                     "weeks": WEEKS, "pulled": datetime.date.fromisoformat(WEEKS[-1]).isoformat(),
                     "buckets": BUCKETS,
                     "note": "per weekly_diag slug. leads=total; by_channel=marketing buckets; by_src=fine tracker sources. _unattributed_national = tracker leads with no clinic locality (national/online: WhatsApp/FB/Google). MARKETING view only."},
           "slugs": acc, "_unattributed_national": unattr}
    json.dump(out, open(os.path.join(ROOT, "data_demand_leads.json"), "w"), separators=(",", ":"))
    natN = [sum(acc[s]["leads"][i] for s in acc) for i in range(N)]
    print(f"wrote data_demand_leads.json · {len(acc)} slugs mapped")
    print(f"  clinic-attributed national (recent 4 wks): {natN[-4:]}")
    print(f"  national UNATTRIBUTED (recent 4 wks): {unattr['leads'][-4:]}")
    print(f"  unattributed by source (latest wk): { {s:a[-1] for s,a in sorted(unattr['by_src'].items(), key=lambda x:-x[1][-1])[:6]} }")


if __name__ == "__main__":
    main()
