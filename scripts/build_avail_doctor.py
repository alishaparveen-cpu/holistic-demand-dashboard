#!/usr/bin/env python3
"""Per-DOCTOR days-attended + days-rostered, weekly, per clinic.
Emits data_avail_doctor.json: {_meta:{weeks:[...]}, clinics:{<slug>:{by_doctor:{<name>:{attend_days,attend_wday,
attend_wend, active_days, wday_days, wend_days}}}}}. Feeds build_quick_diag doctors_block so the city-head
cockpit can show a real per-doctor Availability column. Defs mirror build_availability.py (clinic-level),
validated to match exactly on single-doctor clinics."""
import os, sys, json, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
SQL = open(os.path.join(ROOT, "scripts", "avail_doctor.sql")).read()


def run(sql):
    env = dict(os.environ); env["AWS_PROFILE"] = env.get("AWS_PROFILE", "redshift-data")
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True, env=env)
    if p.returncode != 0:
        sys.stderr.write("query failed:\n" + (p.stderr or "")[:800] + "\n"); sys.exit(1)
    return [ln.split("\t") for ln in p.stdout.splitlines() if ln.strip()]


def norm(n):
    return (n or "").replace("\xa0", " ").strip()


def main():
    rows = run(SQL)   # city, locality, pro_name, week_start, rost_days, rost_wend, rost_wday, att_days, att_wend, att_wday
    weeks = sorted(set(r[3] for r in rows))
    wi = {w: i for i, w in enumerate(weeks)}
    NW = len(weeks)
    Z = lambda: [0] * NW
    clinics = {}
    for r in rows:
        city, loc, pro, wk = r[0], r[1] or "", norm(r[2]), r[3]
        if not pro or wk not in wi:
            continue
        slug = (loc + "_" + city).lower().replace(" ", "_")
        i = wi[wk]
        cl = clinics.setdefault(slug, {})
        d = cl.setdefault(pro, {"active_days": Z(), "wday_days": Z(), "wend_days": Z(),
                                "attend_days": Z(), "attend_wday": Z(), "attend_wend": Z(),
                                "rostered_hrs": Z(), "shrink_hrs": Z()})
        gi = lambda k: int(float(r[k])) if len(r) > k and r[k] not in ("", None) else 0
        gf = lambda k: float(r[k]) if len(r) > k and r[k] not in ("", None) else 0.0
        d["active_days"][i] += gi(4); d["wend_days"][i] += gi(5); d["wday_days"][i] += gi(6)
        d["attend_days"][i] += gi(7); d["attend_wend"][i] += gi(8); d["attend_wday"][i] += gi(9)
        d["rostered_hrs"][i] += gf(10); d["shrink_hrs"][i] += gf(11)
    out = {"_meta": {"weeks": weeks, "source": "avail_doctor.sql (roster_slots blocks + completed offline consults, per provider)",
                     "note": "active_days=rostered days, attend_days=days worked (>=1 completed offline consult), per doctor per clinic"},
           "clinics": {s: {"by_doctor": v} for s, v in clinics.items()}}
    p = os.path.join(ROOT, "data_avail_doctor.json")
    json.dump(out, open(p, "w"), separators=(",", ":"))
    tot_docs = sum(len(v["by_doctor"]) for v in out["clinics"].values())
    print(f"data_avail_doctor.json · {len(clinics)} clinics · {tot_docs} clinic-doctor pairs · {NW} weeks ({weeks[0]}→{weeks[-1]})")


if __name__ == "__main__":
    main()
