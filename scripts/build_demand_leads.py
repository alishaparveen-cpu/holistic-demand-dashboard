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

    wd_cities = {c["city"] for c in wd["clinics"].values()}   # cities the marketing view knows (for the city-level tier)
    city_lc = {c.lower(): c for c in wd_cities}
    Z = lambda: [0]*N
    def blank(): return {"leads": Z(), "by_channel": {b: Z() for b in BUCKETS}, "by_src": {}}
    def add(o, i, fs, n): o["leads"][i] += n; o["by_channel"][bucket(fs)][i] += n; o["by_src"].setdefault(fs, Z())[i] += n
    acc = {}                       # clinic-level  (City|Clinic)
    by_city = {}                   # city-level    (City|NA — a real city, no clinic)
    national = blank()             # national      (NA|NA — no city at all)
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
        if slug:                                              # clinic-level
            add(acc.setdefault(slug, blank()), i, fs, n)
        elif city.strip().lower() in city_lc:                 # city-level (real city, unattributed to a clinic)
            cn = city_lc[city.strip().lower()]
            add(by_city.setdefault(cn, blank()), i, fs, n)
        else:                                                 # truly national (no city)
            add(national, i, fs, n)

    def prune(o):
        o["by_src"] = {s: a for s, a in o["by_src"].items() if sum(a) > 0}
        o["by_channel"] = {b: a for b, a in o["by_channel"].items() if sum(a) > 0}
        return o
    for o in acc.values(): o["by_src"] = {s: a for s, a in o["by_src"].items() if sum(a) > 0}
    for o in by_city.values(): prune(o)
    prune(national)

    out = {"_meta": {"source": "demand_data_week_superset (demand tracker) → marketing leads overlay",
                     "weeks": WEEKS, "pulled": datetime.date.fromisoformat(WEEKS[-1]).isoformat(),
                     "buckets": BUCKETS,
                     "note": "3-tier leads: slugs=clinic-level (City|Clinic); _city_unattr[city]=city-level (City|NA, real city no clinic); _national=NA|NA (no city). by_channel=marketing buckets, by_src=fine sources. MARKETING view only."},
           "slugs": acc, "_city_unattr": by_city, "_national": national,
           "_unattributed_national": national}   # back-compat alias
    json.dump(out, open(os.path.join(ROOT, "data_demand_leads.json"), "w"), separators=(",", ":"))
    cl = [sum(acc[s]["leads"][i] for s in acc) for i in range(N)]
    ci = [sum(by_city[c]["leads"][i] for c in by_city) for i in range(N)]
    print(f"wrote data_demand_leads.json · {len(acc)} clinics · {len(by_city)} cities")
    print(f"  CLINIC-level leads (recent 4 wks): {cl[-4:]}")
    print(f"  CITY-level leads   (recent 4 wks): {ci[-4:]}   cities: {sorted(by_city)[:8]}")
    print(f"  NATIONAL leads     (recent 4 wks): {national['leads'][-4:]}")


if __name__ == "__main__":
    main()
