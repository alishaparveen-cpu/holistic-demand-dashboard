#!/usr/bin/env python3
"""Break each clinic's Revenue into line-item types (drug / lab / consultation / other),
attributed to the completed Screening-Call week — stored on bottom.rev_type so it
reconciles with the displayed Revenue. Resumable (skips clinics with bottom.rev_type).
Run: AWS_PROFILE=redshift-data python3 scripts/patch_rev_type.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import build_clinic_wow as W

ROOT = W.ROOT; OUT = os.path.join(ROOT, "data_source_recon.json")
idx = W.idx; Z = W.Z; LO = W.LO; run_sql = W.run_sql; NW = W.NW
TYPES = ["drug", "lab", "consultation", "other"]

def rev_type_sql(city, loc):
    return """WITH loc AS (SELECT id FROM allo_health.locations WHERE deleted_at IS NULL AND city='{city}' AND locality='{loc}'),
  ap0 AS (SELECT a.id, a.patient_id, TO_CHAR(DATE_TRUNC('week', a.created_at + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk, a.status
    FROM allo_consultations.appointments a JOIN allo_consultations.types typ ON typ.id=a.type_id AND typ.name='Screening Call'
    JOIN loc ON loc.id=a.location_id WHERE a.created_at >= '{lo}' AND a.deleted_at IS NULL),
  ap AS (SELECT id, wk FROM (SELECT ap0.*, ROW_NUMBER() OVER (PARTITION BY patient_id, wk
      ORDER BY (CASE WHEN status='COMPLETED' THEN 0 ELSE 1 END), id) rn FROM ap0) z WHERE rn=1 AND status='COMPLETED')
  SELECT ap.wk, LOWER(ii."type") itype, SUM(ii.payable_amount) amt
  FROM ap JOIN allo_encounters.encounters e ON e.appointment_id=ap.id AND e.deleted_at IS NULL
  JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.status='paid' AND i.deleted_at IS NULL
  JOIN allo_billing.invoice_items ii ON ii.invoice_id=i.id AND ii.deleted_at IS NULL
  GROUP BY 1,2;""".format(city=city.replace("'", "''"), loc=loc.replace("'", "''"), lo=LO)

def rev_type(cfg):
    by = {t: Z() for t in TYPES}
    for line in run_sql(rev_type_sql(cfg["city"], cfg["loc"])):
        c = line.split("\t")
        if len(c) < 3 or c[0] not in idx: continue
        t = c[1] if c[1] in TYPES else "other"; i = idx[c[0]]
        try: by[t][i] += round(int(float(c[2])) / 100.0)
        except ValueError: pass
    return by

if __name__ == "__main__":
    d = json.load(open(OUT)); CFG = W.CFG
    items = list(d["clinics"].items()); done = 0
    for slug, c in items:
        if c.get("bottom", {}).get("rev_type"): continue
        cfg = CFG.get(slug)
        if not cfg: continue
        try:
            c["bottom"]["rev_type"] = rev_type(cfg)
            done += 1
            rt = c["bottom"]["rev_type"]
            print("[ok %d/%d] %s  drug %s lab %s cons %s" % (done, len(items), cfg["disp"],
                  rt["drug"][1], rt["lab"][1], rt["consultation"][1]), flush=True)
            if done % 5 == 0: json.dump(d, open(OUT, "w"), separators=(",", ":"))
        except BaseException as e:
            print("[FAIL] %s: %s" % (cfg.get("disp", slug), type(e).__name__), flush=True)
    json.dump(d, open(OUT, "w"), separators=(",", ":"))
    print("patched %d clinics" % done)
