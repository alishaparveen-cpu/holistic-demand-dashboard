#!/usr/bin/env python3
"""Build data_roster.json — per-clinic weekly roster availability for the diagnostic deep-dive
(Available Hours chart, DOW split, hour-of-day heatmap, shrinkage ladder).

Runs the four roster SQL pulls and assembles them into one file, keyed "City|Clinic":
  hrs    [12]      total distinct slot-hours covered that week        (roster_all.sql)
  we_hrs [12]      of those, on Sat/Sun                               (roster_all.sql)
  dow    [12][7]   slot-hours per day-of-week (0=Sun..6=Sat)          (roster_dow.sql)
  hod    [12][13]  slot-hours per hour-of-day, 09:00–21:00            (roster_hod.sql)
  shr    {sched,shrunk,avail} [12] each — scheduled vs blocked vs bookable slots (roster_shrinkage.sql)
_meta.weeks is newest-first; _meta.hod_hours = [9..21].

NOTE: this builder was lost in a re-clone (only the .sql files were committed) and rebuilt 2026-06-22.
Run:  AWS_PROFILE=redshift-data python3 scripts/build_roster.py
"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ   = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11",
         "2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]
idx = {w: i for i, w in enumerate(WEEKS)}
NW = len(WEEKS)
HOD_HOURS = list(range(9, 22))                    # 9..21 → 13 buckets
hidx = {h: i for i, h in enumerate(HOD_HOURS)}


def run_sql(name):
    sql = open(os.path.join(ROOT, "scripts", name)).read()
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write(f"{name} failed: {(p.stderr or '')[:400]}\n"); sys.exit(1)
    rows = []
    for line in p.stdout.strip().splitlines():
        c = line.split("\t")
        if c and c[0]: rows.append(c)
    return rows


def i(v):
    try: return int(float(v))
    except (ValueError, TypeError): return 0


def main():
    D = {}
    def get(key):
        return D.setdefault(key, {
            "hrs":[0]*NW, "we_hrs":[0]*NW,
            "dow":[[0]*7 for _ in range(NW)],
            "hod":[[0]*len(HOD_HOURS) for _ in range(NW)],
            "shr":{"sched":[0]*NW, "shrunk":[0]*NW, "avail":[0]*NW}})

    for c in run_sql("roster_all.sql"):            # city, clinic, wk, hrs, we_hrs
        if len(c) < 5 or c[2] not in idx: continue
        o = get(f"{c[0]}|{c[1]}"); w = idx[c[2]]
        o["hrs"][w] = i(c[3]); o["we_hrs"][w] = i(c[4])

    for c in run_sql("roster_dow.sql"):            # city, clinic, wk, dow, hrs
        if len(c) < 5 or c[2] not in idx: continue
        d = i(c[3])
        if 0 <= d <= 6: get(f"{c[0]}|{c[1]}")["dow"][idx[c[2]]][d] = i(c[4])

    for c in run_sql("roster_hod.sql"):            # city, clinic, wk, hod, hrs_covered
        if len(c) < 5 or c[2] not in idx: continue
        h = i(c[3])
        if h in hidx: get(f"{c[0]}|{c[1]}")["hod"][idx[c[2]]][hidx[h]] = i(c[4])

    for c in run_sql("roster_shrinkage.sql"):      # city, clinic, wk, sched, shrunk, avail
        if len(c) < 6 or c[2] not in idx: continue
        o = get(f"{c[0]}|{c[1]}")["shr"]; w = idx[c[2]]
        o["sched"][w] = i(c[3]); o["shrunk"][w] = i(c[4]); o["avail"][w] = i(c[5])

    out = dict(D)
    out["_meta"] = {"hod_hours": HOD_HOURS, "weeks": WEEKS,
                    "source": "allo_consultations.roster_slots (screening type, available_for_booking) "
                              "+ appointment_blocks for shrinkage — offline clinics, IST weeks"}
    json.dump(out, open(os.path.join(ROOT, "data_roster.json"), "w"), separators=(",", ":"))
    k = "Bangalore|Indiranagar" if "Bangalore|Indiranagar" in D else (sorted(D)[0] if D else None)
    print(f"data_roster.json · {len(D)} clinics · weeks {WEEKS[-1]}→{WEEKS[0]}"
          + (f" · {k} hrs={D[k]['hrs'][0]} we={D[k]['we_hrs'][0]} avail={D[k]['shr']['avail'][0]}" if k else ""))


if __name__ == "__main__":
    main()
