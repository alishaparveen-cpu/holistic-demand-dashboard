#!/usr/bin/env python3
"""Ops-view bookings — ALL new-patient first-bookings keyed by the BOOKING week (matches the
ops/leadership sheet). Day-granular by booking day-of-week for week-to-date windows.

new-patient booking = a patient whose FIRST-EVER appointment (MIN created_at) is that week.
Our tracked lead->book funnel is a subset; ops total - tracked = untracked (aged web leads,
walk-ins, prior-week callers, Practo) that booked this week with no this-week contact.

Emits data_ops_bookings.json: weeks, opsbk{wk:[7]}  (new-patient bookings by booking day 0=Mon..6=Sun)
Run: AWS_PROFILE=redshift-data python3 scripts/build_ops_bookings.py
"""
import os, sys, json, subprocess
from collections import defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
OUT = os.path.join(ROOT, "data_ops_bookings.json")
FLOOR = "2026-04-13"   # ~12 complete weeks of history for the up-to-10-week toggle

SQL = """
WITH fa AS (SELECT patient_id pid, MIN(DATEADD(minute,330,created_at)) fts
            FROM allo_prod.allo_consultations.appointments WHERE deleted_at IS NULL GROUP BY 1)
SELECT TO_CHAR(DATE_TRUNC('week',fts)::date,'YYYY-MM-DD') week,
  DATEDIFF(day, DATE_TRUNC('week',fts)::date, fts::date) bookday,
  COUNT(*) newbookings
FROM fa WHERE fts >= '{floor}' GROUP BY 1,2;
""".replace("{floor}", FLOOR)


def run(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True,
                       env={**os.environ, "AWS_PROFILE": "redshift-data"})
    out = (p.stdout or "").strip()
    if p.returncode != 0 or out.startswith("FAIL") or "Traceback" in (p.stderr or ""):
        sys.exit("query failed:\n" + (p.stderr or out)[-800:])
    return [ln.split("\t") for ln in out.split("\n") if ln.strip() and not ln.startswith("FAIL")]


if __name__ == "__main__":
    opsbk = defaultdict(lambda: [0] * 7)
    for r in run(SQL):
        if len(r) < 3:
            continue
        wk, d, n = r[0], int(float(r[1])), int(float(r[2]))
        if 0 <= d < 7:
            opsbk[wk][d] += n
    weeks = sorted(opsbk.keys())
    json.dump({"weeks": weeks, "opsbk": opsbk}, open(OUT, "w"), separators=(",", ":"))
    for wk in weeks[-3:]:
        print("%s ops new-patient bookings (full week) %d" % (wk, sum(opsbk[wk])))
    print("wrote", OUT)
