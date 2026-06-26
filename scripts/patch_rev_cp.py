#!/usr/bin/env python3
"""Revenue by CATEGORY × PRODUCT per clinic (STI/SH/MH/Other → drug/lab/consultation/other),
attributed to the completed Screening-Call week, all from invoice line-items so it reconciles
internally. Stored on bottom.rev_cp = {cat: {prod: [weekly ₹]}}.
Resumable (skips clinics with bottom.rev_cp). Run: AWS_PROFILE=redshift-data python3 scripts/patch_rev_cp.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import build_clinic_wow as W

ROOT = W.ROOT; OUT = os.path.join(ROOT, "data_source_recon.json")
idx = W.idx; Z = W.Z; LO = W.LO; run_sql = W.run_sql
CATS = ["STI", "SH", "MH", "Other"]; PRODS = ["drug", "lab", "consultation", "other"]

def rev_cp_sql(city, loc):
    return """WITH loc AS (SELECT id FROM allo_health.locations WHERE deleted_at IS NULL AND city='{city}' AND locality='{loc}'),
  etag AS (SELECT e.appointment_id ap_id,
      MAX(CASE WHEN et.tag_type='sti' THEN 1 ELSE 0 END) t_sti,
      MAX(CASE WHEN et.tag_type IN ('ed_plus_pe_plus','ed_plus','pe_plus','nssd') THEN 1 ELSE 0 END) t_sh,
      MAX(CASE WHEN et.tag_type='others' THEN 1 ELSE 0 END) t_oth
    FROM allo_encounters.encounters e
    LEFT JOIN allo_analytics.encounter_tags et ON et.encounter_id=e.id AND et.tag_category='diagnosis' AND et.deleted_at IS NULL
    WHERE e.deleted_at IS NULL GROUP BY 1),
  diag AS (SELECT e.appointment_id ap_id,
      MAX(CASE WHEN d.description ILIKE '%porn%' OR d.description ILIKE '%masturbat%' OR d.description ILIKE '%sex%addict%'
               OR d.description ILIKE '%performance anxiety%' OR d.description ILIKE '%sexual%anxiety%' THEN 1 ELSE 0 END) d_sexual,
      MAX(CASE WHEN d.description LIKE '%(6A%' OR d.description LIKE '%(6B%' OR d.description LIKE '%(6C%' OR d.description LIKE '%(6D%'
               OR d.description LIKE '%(6E%' OR d.description ILIKE '%anxiety%' OR d.description ILIKE '%depress%' OR d.description ILIKE '%adhd%'
               OR d.description ILIKE '%psychosis%' OR d.description ILIKE '%bipolar%' OR d.description ILIKE '%personality%' OR d.description ILIKE '%nicotine%'
               OR d.description ILIKE '%addiction%' OR d.description ILIKE '%adjustment%' OR d.description ILIKE '%ptsd%' THEN 1 ELSE 0 END) d_mh
    FROM allo_encounters.encounters e JOIN allo_observations.diagnoses d ON d.encounter_id=e.id AND d.deleted_at IS NULL
    WHERE e.deleted_at IS NULL GROUP BY 1),
  ap0 AS (SELECT a.id, a.patient_id, TO_CHAR(DATE_TRUNC('week', a.created_at + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk
    FROM allo_consultations.appointments a JOIN allo_consultations.types typ ON typ.id=a.type_id AND typ.name='Screening Call'
    JOIN loc ON loc.id=a.location_id WHERE a.created_at >= '{lo}' AND a.deleted_at IS NULL AND a.status='COMPLETED'),
  ap AS (SELECT id, wk FROM (SELECT ap0.*, ROW_NUMBER() OVER (PARTITION BY patient_id, wk ORDER BY id) rn FROM ap0) z WHERE rn=1)
  SELECT ap.wk,
    CASE WHEN COALESCE(et.t_sti,0)=1 THEN 'STI' WHEN COALESCE(et.t_sh,0)=1 THEN 'SH'
         WHEN COALESCE(dg.d_sexual,0)=1 THEN 'SH'
         WHEN COALESCE(dg.d_mh,0)=1 THEN 'MH' WHEN COALESCE(et.t_oth,0)=1 THEN 'SH' ELSE 'Other' END cat,
    LOWER(ii."type") itype, SUM(ii.payable_amount) amt
  FROM ap JOIN allo_encounters.encounters e ON e.appointment_id=ap.id AND e.deleted_at IS NULL
  LEFT JOIN etag et ON et.ap_id=ap.id LEFT JOIN diag dg ON dg.ap_id=ap.id
  JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.status='paid' AND i.deleted_at IS NULL
  JOIN allo_billing.invoice_items ii ON ii.invoice_id=i.id AND ii.deleted_at IS NULL
  GROUP BY 1,2,3;""".format(city=city.replace("'", "''"), loc=loc.replace("'", "''"), lo=LO)

def rev_cp(cfg):
    by = {c: {p: Z() for p in PRODS} for c in CATS}
    for line in run_sql(rev_cp_sql(cfg["city"], cfg["loc"])):
        c = line.split("\t")
        if len(c) < 4 or c[0] not in idx: continue
        cat = c[1] if c[1] in CATS else "Other"
        prod = c[2] if c[2] in PRODS else "other"; i = idx[c[0]]
        try: by[cat][prod][i] += round(int(float(c[3])) / 100.0)
        except ValueError: pass
    return by

if __name__ == "__main__":
    d = json.load(open(OUT)); CFG = W.CFG
    items = list(d["clinics"].items()); done = 0
    for slug, c in items:
        if c.get("bottom", {}).get("rev_cp"): continue
        cfg = CFG.get(slug)
        if not cfg: continue
        try:
            c["bottom"]["rev_cp"] = rev_cp(cfg); done += 1
            print("[ok %d/%d] %s" % (done, len(items), cfg["disp"]), flush=True)
            if done % 5 == 0: json.dump(d, open(OUT, "w"), separators=(",", ":"))
        except BaseException as e:
            print("[FAIL] %s: %s" % (cfg.get("disp", slug), type(e).__name__), flush=True)
    json.dump(d, open(OUT, "w"), separators=(",", ":"))
    print("patched %d clinics" % done)
