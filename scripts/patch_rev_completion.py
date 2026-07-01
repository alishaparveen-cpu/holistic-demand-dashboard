#!/usr/bin/env python3
"""Rebase REVENUE (by product & category) to the SC-DONE (completion) week, consolidating
payments that landed in other weeks back to the week the screening call was completed.

For every COMPLETED SC (bucketed by completion week = actual_start_time), sum that encounter's
PAID invoice line-items (drug / lab / consultation / other), regardless of when the invoice was
paid. So "revenue from week W's done cohort" = what those SCs eventually billed & collected,
credited to W. Based on the SC encounter only.

Overwrites per clinic: bottom.rev_cp = {cat:{product:[52]}}, bottom.rev_type = {product:[52]},
and bottom.rev = Σ (so the displayed Revenue + its product/category splits are all done-week
consolidated and reconcile). Run: AWS_PROFILE=redshift-data python3 scripts/patch_rev_completion.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import patch_subcat as PS
ROOT = PS.ROOT; OUT = os.path.join(ROOT, "data_source_recon.json")
idx = PS.idx; Z = PS.Z; LO = PS.LO; run_sql = PS.run_sql; SUBCASE = PS.SUBCASE
CATS = ["STI", "SH", "MH", "Other"]; PRODS = ["drug", "lab", "consultation", "other"]

SQL = """WITH etag AS (SELECT e.appointment_id ap_id,
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
  comp AS (SELECT a.id, loc.city ct, loc.locality lc,
      TO_CHAR(DATE_TRUNC('week', COALESCE(a.actual_start_time,a.start_time,a.created_at) + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') cwk,
      ROW_NUMBER() OVER (PARTITION BY a.patient_id, loc.city, loc.locality,
        DATE_TRUNC('week', COALESCE(a.actual_start_time,a.start_time,a.created_at) + INTERVAL '5 hours 30 minutes') ORDER BY a.id) rn
    FROM allo_consultations.appointments a
    JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
    JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.deleted_at IS NULL AND loc.locality IS NOT NULL AND loc.locality<>''
    WHERE a.deleted_at IS NULL AND a.status='COMPLETED'
      AND COALESCE(a.actual_start_time,a.start_time,a.created_at) >= '{lo}'
      AND COALESCE(a.actual_start_time,a.start_time,a.created_at) < '2026-06-29'),
  items AS (SELECT e.appointment_id ap_id,
      CASE WHEN LOWER(ii."type") IN ('drug','lab','consultation') THEN LOWER(ii."type") ELSE 'other' END prod,
      SUM(ii.payable_amount) amt
    FROM allo_encounters.encounters e
    JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.status='paid' AND i.deleted_at IS NULL
    JOIN allo_billing.invoice_items ii ON ii.invoice_id=i.id AND ii.deleted_at IS NULL
    WHERE e.deleted_at IS NULL GROUP BY 1,2)
SELECT c.ct, c.lc, c.cwk, SPLIT_PART({subcase},'::',1) cat, items.prod, SUM(items.amt) amt
FROM comp c JOIN items ON items.ap_id=c.id
  LEFT JOIN etag et ON et.ap_id=c.id LEFT JOIN diag dg ON dg.ap_id=c.id
WHERE c.rn=1
GROUP BY 1,2,3,4,5;""".format(lo=LO, subcase=SUBCASE)

def slugify(loc, city):
    s = lambda x: "".join(ch if ch.isalnum() else "_" for ch in (x or "").strip().lower())
    return s(loc) + "_" + s(city)
CITY_ALIAS = {"bengaluru": "bangalore", "gurgaon": "gurugram"}
def norm_city(c): c = (c or "").strip().lower(); return CITY_ALIAS.get(c, c)

if __name__ == "__main__":
    d = json.load(open(OUT)); clinics = d["clinics"]
    cp = {}    # slug -> cat -> prod -> [weeks]
    for line in run_sql(SQL):
        r = line.split("\t") if isinstance(line, str) else line
        if len(r) < 6: continue
        ct, lc, cwk, cat, prod, amt = r[:6]
        if cwk not in idx: continue
        if cat not in CATS: cat = "Other"
        if prod not in PRODS: prod = "other"
        slug = slugify(lc, norm_city(ct)); i = idx[cwk]
        try: rs = round(int(float(amt)) / 100.0)
        except (ValueError, TypeError): continue
        cp.setdefault(slug, {c: {p: Z() for p in PRODS} for c in CATS})[cat][prod][i] += rs

    matched = 0
    for slug, c in clinics.items():
        if slug not in cp: continue
        d_cp = cp[slug]
        c["bottom"]["rev_cp"] = {cat: {p: d_cp[cat][p] for p in PRODS if any(d_cp[cat][p])} for cat in CATS if any(any(d_cp[cat][p]) for p in PRODS)}
        rt = {p: Z() for p in PRODS}
        for cat in CATS:
            for p in PRODS:
                for i in range(len(Z())): rt[p][i] += d_cp[cat][p][i]
        c["bottom"]["rev_type"] = {p: rt[p] for p in PRODS if any(rt[p])}
        c["bottom"]["rev"] = [sum(rt[p][i] for p in PRODS) for i in range(len(Z()))]
        c["bottom"]["rev_done_week"] = True
        matched += 1
    json.dump(d, open(OUT, "w"), separators=(",", ":"))
    tot = sum(sum(c["bottom"]["rev"]) for c in clinics.values() if c.get("bottom", {}).get("rev_done_week"))
    print("rebased revenue (done-week, by product) for %d clinics | network rev Rs%.2f Cr" % (matched, tot / 1e7))
