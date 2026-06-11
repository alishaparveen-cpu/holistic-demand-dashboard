#!/usr/bin/env python3
"""Pull per-clinic realized revenue → data_clinic_revenue.json (Stage 8 of the clinic funnel).
Realized revenue = SUM(allo_billing.invoices.amount WHERE status='paid') over COMPLETED Screening
Calls, attributed to the appointment's clinic (allo_health.locations city+locality), by week.
amount is in paise → /100 = ₹. Same join chain as the efficiency revenue block (validated vs L0).

Per "City|Clinic": rev[12] (₹) · paid_consults[12]  — newest-first, aligned to the dashboard weeks.
Run:  AWS_PROFILE=redshift-data python3 scripts/pull_clinic_revenue.py
"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27",
         "2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23","2026-03-16"]
idx = {w: i for i, w in enumerate(WEEKS)}
NW = len(WEEKS)

SQL = """WITH loc AS (
    SELECT id, MAX(city) city, MAX(locality) locality
    FROM allo_health.locations WHERE deleted_at IS NULL AND is_active=1 GROUP BY id),
  ap AS (
    SELECT a.id, TO_CHAR(DATE_TRUNC('week', a.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk,
           l.city, l.locality
    FROM allo_consultations.appointments a
    JOIN allo_consultations.types typ ON typ.id=a.type_id AND typ.name='Screening Call'
    JOIN loc l ON l.id=a.location_id
    WHERE a.start_time >= '2026-03-16' AND a.start_time < '2026-06-08'
      AND a.deleted_at IS NULL AND a.status='COMPLETED'
      AND l.locality IS NOT NULL AND LOWER(l.locality) <> 'online' AND l.city <> 'Practo Online'),
  inv AS (
    SELECT e.appointment_id ap_id, SUM(i.amount) amt
    FROM allo_encounters.encounters e
    JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.deleted_at IS NULL AND i.status='paid'
    WHERE e.deleted_at IS NULL GROUP BY 1)
  SELECT ap.city, ap.locality, ap.wk,
         SUM(COALESCE(inv.amt,0)) rev_paise,
         COUNT(inv.ap_id) paid_consults
  FROM ap LEFT JOIN inv ON inv.ap_id=ap.id
  GROUP BY 1,2,3 ORDER BY 1,2,3;"""


def main():
    p = subprocess.run([sys.executable, RQ], input=SQL, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("revenue query failed: " + (p.stderr or "")[:400] + "\n"); sys.exit(1)
    D = {}
    for line in p.stdout.strip().splitlines():
        c = line.split("\t")
        if len(c) < 5: continue
        city, loc, wk, rev_paise, n = c[0], c[1], c[2], c[3], c[4]
        if wk not in idx: continue
        key = f"{city}|{loc}"
        o = D.setdefault(key, {"rev": [0.0]*NW, "paid_consults": [0]*NW})
        i = idx[wk]
        try:
            o["rev"][i] += round(int(float(rev_paise)) / 100.0)   # paise → ₹
            o["paid_consults"][i] += int(float(n))
        except ValueError:
            pass
    for o in D.values():
        o["rev"] = [round(x) for x in o["rev"]]
    out = {"_meta": {"weeks": WEEKS,
                     "source": "allo_billing.invoices (status=paid) × COMPLETED Screening Calls × location · ₹ per clinic-week",
                     "fields": "rev=paid invoice ₹ that week (slot-week, IST); paid_consults=consults with a paid invoice"}}
    out.update(D)
    json.dump(out, open(os.path.join(ROOT, "data_clinic_revenue.json"), "w"), separators=(",", ":"))
    tot = sum(sum(o["rev"]) for o in D.values())
    w0 = sum(o["rev"][0] for o in D.values())
    print(f"data_clinic_revenue.json · {len(D)} clinics · 12-wk total ₹{tot:,.0f} · latest week ₹{w0:,.0f}")
    # sample top 5 clinics by latest-week revenue
    top = sorted(D.items(), key=lambda kv: -kv[1]["rev"][0])[:5]
    for k, o in top:
        print(f"  {k:34} W0 ₹{o['rev'][0]:>8,} · {o['paid_consults'][0]} paid consults")


if __name__ == "__main__":
    main()
