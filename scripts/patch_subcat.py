#!/usr/bin/env python3
"""Recompute category + add SUB-CATEGORY split per clinic, correcting the porn-addiction /
performance-anxiety leak into MH (they are sexual -> SH). MH becomes clinical-only.
Overwrites bottom.by_cat (STI/SH/MH/Other, corrected) and adds bottom.by_subcat
= {"CAT::SUB": {cat, booked[], done[], purchased[], rev[]}} attributed to the SC week.
Resumable (skips clinics with bottom.by_subcat).
Run: AWS_PROFILE=redshift-data python3 scripts/patch_subcat.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import build_clinic_wow as W

ROOT = W.ROOT; OUT = os.path.join(ROOT, "data_source_recon.json")
idx = W.idx; Z = W.Z; LO = W.LO; run_sql = W.run_sql; CATS = ["STI", "SH", "MH", "Other"]
FIELDS = ("booked", "done", "purchased", "rev")

# sub-category CASE -> 'CAT::SUB' (precedence: STI tag, ED/PE tags, sexual diagnoses, clinical MH, screened-clear, others->SH, Other)
SUBCASE = """CASE
    WHEN et.t_sti=1 THEN 'STI::STI'
    WHEN et.t_edpe=1 THEN 'SH::ED+PE' WHEN et.t_ed=1 THEN 'SH::ED' WHEN et.t_pe=1 THEN 'SH::PE'
    WHEN dg.d_porn=1 THEN 'SH::Porn/Sex addiction' WHEN dg.d_pfx=1 THEN 'SH::Performance anxiety'
    WHEN dg.d_lowdes=1 THEN 'SH::Low desire' WHEN dg.d_femsex=1 THEN 'SH::Female sexual'
    WHEN dg.d_foreskin=1 THEN 'SH::Foreskin/Penile' WHEN dg.d_dejac=1 THEN 'SH::Delayed ejaculation'
    WHEN dg.d_stic=1 THEN 'SH::STI-concern'
    WHEN dg.d_dep=1 THEN 'MH::Depression' WHEN dg.d_adhd=1 THEN 'MH::ADHD' WHEN dg.d_ocd=1 THEN 'MH::OCD'
    WHEN dg.d_bip=1 THEN 'MH::Bipolar' WHEN dg.d_ptsd=1 THEN 'MH::PTSD' WHEN dg.d_adj=1 THEN 'MH::Adjustment'
    WHEN dg.d_sub=1 THEN 'MH::Substance' WHEN dg.d_psych=1 THEN 'MH::Psychosis'
    WHEN dg.d_anx=1 THEN 'MH::Anxiety' WHEN dg.d_mh=1 THEN 'MH::Other'
    WHEN dg.d_nodis=1 OR et.t_nssd=1 THEN 'SH::No disorder (screened)'
    WHEN et.t_oth=1 THEN 'SH::Other sexual' ELSE 'Other::Other' END"""

def subcat_sql(city, loc):
    return """WITH loc AS (SELECT id FROM allo_health.locations WHERE deleted_at IS NULL AND city='{city}' AND locality='{loc}'),
  etag AS (SELECT e.appointment_id ap_id,
      MAX(CASE WHEN et.tag_type='sti' THEN 1 ELSE 0 END) t_sti,
      MAX(CASE WHEN et.tag_type='ed_plus_pe_plus' THEN 1 ELSE 0 END) t_edpe,
      MAX(CASE WHEN et.tag_type='ed_plus' THEN 1 ELSE 0 END) t_ed,
      MAX(CASE WHEN et.tag_type='pe_plus' THEN 1 ELSE 0 END) t_pe,
      MAX(CASE WHEN et.tag_type='nssd' THEN 1 ELSE 0 END) t_nssd,
      MAX(CASE WHEN et.tag_type='others' THEN 1 ELSE 0 END) t_oth
    FROM allo_encounters.encounters e
    LEFT JOIN allo_analytics.encounter_tags et ON et.encounter_id=e.id AND et.tag_category='diagnosis' AND et.deleted_at IS NULL
    WHERE e.deleted_at IS NULL GROUP BY 1),
  diag AS (SELECT e.appointment_id ap_id,
      MAX(CASE WHEN d.description ILIKE '%porn%' OR d.description ILIKE '%masturbat%' OR d.description ILIKE '%sex%addict%' OR d.description ILIKE '%compulsive sexual%' THEN 1 ELSE 0 END) d_porn,
      MAX(CASE WHEN d.description ILIKE '%performance anxiety%' OR d.description ILIKE '%sexual%anxiety%' THEN 1 ELSE 0 END) d_pfx,
      MAX(CASE WHEN d.description ILIKE '%low sexual desire%' OR d.description ILIKE '%low desire%' OR d.description ILIKE '%low libido%' OR d.description ILIKE '%hypoactive%' THEN 1 ELSE 0 END) d_lowdes,
      MAX(CASE WHEN d.description ILIKE '%vaginismus%' OR d.description ILIKE '%dyspareunia%' OR d.description ILIKE '%anorgasmia%' OR d.description ILIKE '%arousal disorder%' OR d.description ILIKE '%fsad%' OR d.description ILIKE '%pain during sex%' OR d.description ILIKE '%female sexual%' THEN 1 ELSE 0 END) d_femsex,
      MAX(CASE WHEN d.description ILIKE '%balanitis%' OR d.description ILIKE '%phimosis%' OR d.description ILIKE '%balanoposthitis%' THEN 1 ELSE 0 END) d_foreskin,
      MAX(CASE WHEN d.description ILIKE '%delayed ejaculation%' THEN 1 ELSE 0 END) d_dejac,
      MAX(CASE WHEN d.description ILIKE '%?sti%' OR d.description ILIKE '%fear of sti%' OR d.description ILIKE '%sti scare%' OR d.description ILIKE '%sti concern%' THEN 1 ELSE 0 END) d_stic,
      MAX(CASE WHEN (d.description ILIKE '%no symptomatic sexual%' OR d.description ILIKE '%no sexual disorder%' OR d.description ILIKE '%no sexual dysfunction%' OR d.description ILIKE '%nssd%') THEN 1 ELSE 0 END) d_nodis,
      MAX(CASE WHEN d.description ILIKE '%depress%' THEN 1 ELSE 0 END) d_dep,
      MAX(CASE WHEN d.description ILIKE '%adhd%' THEN 1 ELSE 0 END) d_adhd,
      MAX(CASE WHEN d.description ILIKE '%obsessive%' OR d.description ILIKE '%ocd%' THEN 1 ELSE 0 END) d_ocd,
      MAX(CASE WHEN d.description ILIKE '%bipolar%' THEN 1 ELSE 0 END) d_bip,
      MAX(CASE WHEN d.description ILIKE '%ptsd%' OR d.description ILIKE '%grief%' THEN 1 ELSE 0 END) d_ptsd,
      MAX(CASE WHEN d.description ILIKE '%adjustment%' THEN 1 ELSE 0 END) d_adj,
      MAX(CASE WHEN d.description ILIKE '%alcohol%' OR d.description ILIKE '%nicotine%' OR d.description LIKE '%(6C4%' THEN 1 ELSE 0 END) d_sub,
      MAX(CASE WHEN d.description ILIKE '%psychosis%' OR d.description ILIKE '%schizophren%' OR d.description ILIKE '%delusional%' THEN 1 ELSE 0 END) d_psych,
      MAX(CASE WHEN d.description ILIKE '%anxiety%' OR d.description ILIKE '%panic%' OR d.description ILIKE '%agoraphobia%' THEN 1 ELSE 0 END) d_anx,
      MAX(CASE WHEN d.description LIKE '%(6A%' OR d.description LIKE '%(6B%' OR d.description LIKE '%(6C%' OR d.description LIKE '%(6D%' OR d.description LIKE '%(6E%' OR d.description ILIKE '%personality%' OR d.description ILIKE '%somatoform%' THEN 1 ELSE 0 END) d_mh
    FROM allo_encounters.encounters e JOIN allo_observations.diagnoses d ON d.encounter_id=e.id AND d.deleted_at IS NULL
    WHERE e.deleted_at IS NULL GROUP BY 1),
  ap0 AS (SELECT a.id, a.patient_id, TO_CHAR(DATE_TRUNC('week', a.created_at + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk, a.status
    FROM allo_consultations.appointments a JOIN allo_consultations.types typ ON typ.id=a.type_id AND typ.name='Screening Call'
    JOIN loc ON loc.id=a.location_id WHERE a.created_at >= '{lo}' AND a.deleted_at IS NULL),
  ap AS (SELECT id, wk, status FROM (SELECT ap0.*, ROW_NUMBER() OVER (PARTITION BY patient_id, wk
      ORDER BY (CASE WHEN status='COMPLETED' THEN 0 ELSE 1 END), id) rn FROM ap0) z WHERE rn=1),
  inv AS (SELECT e.appointment_id ap_id, SUM(i.amount) amt FROM allo_encounters.encounters e
    JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.deleted_at IS NULL AND i.status='paid' WHERE e.deleted_at IS NULL GROUP BY 1)
  SELECT ap.wk, {subcase} subcat,
    COUNT(*) booked, SUM(CASE WHEN ap.status='COMPLETED' THEN 1 ELSE 0 END) done,
    COUNT(CASE WHEN ap.status='COMPLETED' AND inv.ap_id IS NOT NULL THEN 1 END) purchased,
    SUM(CASE WHEN ap.status='COMPLETED' THEN COALESCE(inv.amt,0) ELSE 0 END) rev_paise
  FROM ap LEFT JOIN etag et ON et.ap_id=ap.id LEFT JOIN diag dg ON dg.ap_id=ap.id LEFT JOIN inv ON inv.ap_id=ap.id
  GROUP BY 1,2 ORDER BY 1,2;""".format(city=city.replace("'", "''"), loc=loc.replace("'", "''"), lo=LO, subcase=SUBCASE)

def blank(): return {k: Z() for k in FIELDS}

def compute(cfg):
    by_sub = {}; by_cat = {c: blank() for c in CATS}
    for line in run_sql(subcat_sql(cfg["city"], cfg["loc"])):
        c = line.split("\t")
        if len(c) < 6 or c[0] not in idx: continue
        wk, sub = c[0], c[1]; i = idx[wk]
        cat = sub.split("::")[0]
        if cat not in CATS: cat = "Other"
        if sub not in by_sub: by_sub[sub] = {"cat": cat, **blank()}
        def add(d, field, val):
            try: d[field][i] += int(float(val))
            except (ValueError, TypeError): pass
        add(by_sub[sub], "booked", c[2]); add(by_cat[cat], "booked", c[2])
        add(by_sub[sub], "done", c[3]); add(by_cat[cat], "done", c[3])
        add(by_sub[sub], "purchased", c[4]); add(by_cat[cat], "purchased", c[4])
        try:
            rv = round(int(float(c[5])) / 100.0)
            by_sub[sub]["rev"][i] += rv; by_cat[cat]["rev"][i] += rv
        except (ValueError, TypeError): pass
    return by_cat, by_sub

if __name__ == "__main__":
    d = json.load(open(OUT)); CFG = W.CFG
    items = list(d["clinics"].items()); done = 0
    for slug, c in items:
        if c.get("bottom", {}).get("by_subcat"): continue
        cfg = CFG.get(slug)
        if not cfg: continue
        try:
            by_cat, by_sub = compute(cfg)
            c["bottom"]["by_cat"] = by_cat        # corrected categorisation
            c["bottom"]["by_subcat"] = by_sub     # new sub-category level
            done += 1
            print("[ok %d/%d] %s  subs=%d" % (done, len(items), cfg["disp"], len(by_sub)), flush=True)
            if done % 5 == 0: json.dump(d, open(OUT, "w"), separators=(",", ":"))
        except BaseException as e:
            print("[FAIL] %s: %s" % (cfg.get("disp", slug), type(e).__name__), flush=True)
    json.dump(d, open(OUT, "w"), separators=(",", ":"))
    print("patched %d clinics" % done)
