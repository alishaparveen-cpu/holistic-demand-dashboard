#!/usr/bin/env python3
"""Build data_daily.json — DAILY demand pulse for Quick View's daily toggle.
Last 35 days up to YESTERDAY (GBP/booking data for today is incomplete). Three series per entity:
  bk   = Screening-Call appointments CREATED that day (booking velocity — demand made today)
  done = Screening-Call appointments whose slot was that day AND attended (consults completed)
  leads= (network only) leads CREATED that day in main_source_wise_leads (inbound demand)

Per-clinic keyed "City|Clinic" with {bk,done}; "_network" adds leads. City/tier aggregate in JS.
Arrays are oldest→newest aligned to _meta.days. Offline clinics only (locality<>'online').
Run: AWS_PROFILE=redshift-data python3 scripts/build_daily.py"""
import os, sys, subprocess, json, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")

# yesterday (IST-ish; data for "today" is partial) and a 35-day window
TODAY = datetime.date.today()
END = TODAY                                   # exclusive upper bound → includes through yesterday
START = END - datetime.timedelta(days=35)
DAYS = [(START + datetime.timedelta(days=i)).isoformat() for i in range((END - START).days)]  # oldest→newest
idx = {d: i for i, d in enumerate(DAYS)}
ND = len(DAYS)


def run(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("query failed: " + (p.stderr or "")[:400] + "\n"); sys.exit(1)
    return [ln.split("\t") for ln in p.stdout.strip().splitlines() if ln.strip()]


def main():
    s, e = START.isoformat(), END.isoformat()
    # ── bookings (created) + done (attended) per clinic per day ──
    bd_sql = f"""
WITH sc AS (
  SELECT app.id, app.created_at, app.start_time, app.status, loc.city, loc.locality
  FROM allo_consultations.appointments app
  JOIN allo_health.locations loc ON app.location_id=loc.id AND loc.deleted_at IS NULL
  JOIN allo_consultations.types typ ON app.type_id=typ.id AND typ.name='Screening Call'
  WHERE app.deleted_at IS NULL
    AND LOWER(COALESCE(loc.locality,'')) <> 'online' AND loc.locality IS NOT NULL
)
SELECT city, locality, kind, d, n FROM (
  SELECT city, locality, 'bk' AS kind,
    TO_CHAR(DATE_TRUNC('day', created_at + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS d, COUNT(*) AS n
  FROM sc WHERE created_at >= '{s}' AND created_at < '{e}' GROUP BY 1,2,4
  UNION ALL
  SELECT city, locality, 'done' AS kind,
    TO_CHAR(DATE_TRUNC('day', start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS d, COUNT(*) AS n
  FROM sc WHERE start_time >= '{s}' AND start_time < '{e}' AND LOWER(status) IN ('done','completed')
  GROUP BY 1,2,4
) ORDER BY 1,2,3,4"""
    D = {}
    net = {"bk": [0]*ND, "done": [0]*ND, "leads": [0]*ND}
    for c in run(bd_sql):
        if len(c) < 5: continue
        city, loc, kind, d, n = c[0], c[1], c[2], c[3], c[4]
        if d not in idx: continue
        try: n = int(float(n))
        except ValueError: continue
        key = f"{city}|{loc}"
        o = D.setdefault(key, {"bk": [0]*ND, "done": [0]*ND})
        o[kind][idx[d]] += n
        net[kind][idx[d]] += n

    # ── network leads created per day ──
    ld_sql = f"""
SELECT TO_CHAR(DATE_TRUNC('day', created_on + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS d, COUNT(*) AS n
FROM production.public.main_source_wise_leads
WHERE created_on >= '{s}' AND created_on < '{e}' GROUP BY 1 ORDER BY 1"""
    for c in run(ld_sql):
        if len(c) < 2: continue
        d, n = c[0], c[1]
        if d not in idx: continue
        try: net["leads"][idx[d]] += int(float(n))
        except ValueError: pass

    out = {"_meta": {"source": "allo_consultations.appointments (SC) + main_source_wise_leads · DAILY",
                     "days": DAYS, "generated_for": "up to " + (END - datetime.timedelta(days=1)).isoformat(),
                     "fields": "bk=SC appts CREATED that day (booking velocity); done=SC slot that day & attended; leads=network leads created (network only)"},
           "_network": net}
    out.update(D)
    json.dump(out, open(os.path.join(ROOT, "data_daily.json"), "w"), separators=(",", ":"))
    tb = sum(net["bk"]); td = sum(net["done"]); tl = sum(net["leads"])
    print(f"data_daily.json · {len(D)} clinics · {ND} days ({DAYS[0]}→{DAYS[-1]})")
    print(f"network 35d totals: bookings {tb} · done {td} · leads {tl}")
    print("network bookings/day (last 10):", net["bk"][-10:])
    print("network leads/day    (last 10):", net["leads"][-10:])


if __name__ == "__main__":
    main()
