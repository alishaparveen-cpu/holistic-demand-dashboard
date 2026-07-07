#!/usr/bin/env python3
"""Build data_prescribe.json — Prescribed→Purchase per line (meds/tests/therapy), OFFLINE SC, per clinic + doctor, weekly.
Prescribed = an order exists (allo_drugs/labs/consultations orders); Purchased = paid invoice line item of that type.
Keyed 'city|locality' (doctor's block clinic) + by_doctor. Run: AWS_PROFILE=redshift-data python3 scripts/build_prescribe.py
"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
SQL = open(os.path.join(ROOT, "scripts", "prescribe.sql")).read()
FIELDS = ["meds_pres", "meds_purch", "test_pres", "test_purch", "ther_pres", "ther_purch", "any_pres", "any_purch"]


def run(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("query failed:\n" + (p.stderr or "")[:1000] + "\n"); sys.exit(1)
    return [ln.split("\t") for ln in p.stdout.strip().splitlines() if ln.strip()]


def main():
    rows = run(SQL)
    weeks = sorted({r[3] for r in rows})
    widx = {w: i for i, w in enumerate(weeks)}
    NW = len(weeks)
    blank = lambda: {f: [0]*NW for f in FIELDS}
    clinics = {}
    for r in rows:
        city, loc, doctor, wk = r[0], r[1], r[2], r[3]
        key = city + "|" + loc
        i = widx[wk]
        vals = [int(float(x)) for x in r[4:12]]
        o = clinics.setdefault(key, blank())
        dd = o.setdefault("by_doctor", {}).setdefault(doctor, blank())
        for f, v in zip(FIELDS, vals):
            o[f][i] += v; dd[f][i] += v
    out = {"_meta": {"weeks": weeks, "source": "L2 prescription query (allo_drugs/labs/consultations orders) · offline SC · doctor's block clinic",
                     "note": "prescribed = order exists; purchased = paid invoice line item of that type. Keyed city|locality + by_doctor.",
                     "fields": FIELDS},
           "clinics": clinics}
    json.dump(out, open(os.path.join(ROOT, "data_prescribe.json"), "w"), separators=(",", ":"))
    mp = sum(sum(o["meds_pres"]) for o in clinics.values()); mpu = sum(sum(o["meds_purch"]) for o in clinics.values())
    print(f"data_prescribe.json · {len(clinics)} clinic-keys · {NW} weeks ({weeks[0]}→{weeks[-1]}) · meds prescribed {mp} purchased {mpu} · P2P {round(100*mpu/max(1,mp))}%")


if __name__ == "__main__":
    main()
