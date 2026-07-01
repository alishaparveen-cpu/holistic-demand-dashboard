#!/usr/bin/env python3
"""Rebase the DONE side of the old funnels to the COMPLETION week (when the consult actually
happened), not the booking-creation week. So "done this week" = consults that actually took
place this week, incl. ones booked in an earlier week.

Completion week = DATE_TRUNC('week', COALESCE(actual_start_time, start_time, created_at)).
Rebuilds (bucketed by completion week): bottom.done/purchased/rev, bottom.by_cat[cat].done/
purchased/rev, bottom.by_subcat[sub].done/purchased/rev, done_by_source, done_cat_source.
BOOKED side + book_cohort are untouched (bookings stay on booking-week = demand-this-week).

Validates each clinic's done/purchased/rev TOTALS still reconcile to the existing totals
(same completions, only the week moves). Adds bottom.done_by_completion flag. One network query.
Run: AWS_PROFILE=redshift-data python3 scripts/patch_done_by_completion.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import patch_subcat as PS
import patch_demand_first as PD          # SRC_CASE, GMB_IN, GOOG_IN, SOURCES (loads exophone xlsx on import)
ROOT = PS.ROOT; OUT = os.path.join(ROOT, "data_source_recon.json")
idx = PS.idx; Z = PS.Z; LO = PS.LO; run_sql = PS.run_sql; SUBCASE = PS.SUBCASE
CATS = ["STI", "SH", "MH", "Other"]; SOURCES = PD.SOURCES

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
  inv AS (SELECT e.appointment_id ap_id, SUM(i.amount) amt FROM allo_encounters.encounters e
    JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.deleted_at IS NULL AND i.status='paid' WHERE e.deleted_at IS NULL GROUP BY 1),
  gc AS (SELECT DISTINCT RIGHT("from",10) ph FROM allo_vendors.exotel_calls
        WHERE RIGHT(exotel_number,10) IN ('{gmb}') AND routed_to='lead_to_call' AND direction='inbound' AND start_time>='2025-06-23'),
  pc AS (SELECT DISTINCT RIGHT("from",10) ph FROM allo_vendors.exotel_calls
        WHERE RIGHT(exotel_number,10) IN ('{goog}') AND routed_to='lead_to_call' AND direction='inbound' AND start_time>='2025-06-23'),
  u AS (SELECT ph,us,um,g,f FROM (
     SELECT RIGHT(phone_no,10) ph, LOWER(COALESCE(utm_source,'')) us, LOWER(COALESCE(utm_medium,'')) um,
       CASE WHEN gclid<>'' THEN 1 ELSE 0 END g, CASE WHEN fbclid<>'' THEN 1 ELSE 0 END f,
       ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY created_at DESC) rn
     FROM allo_persons.lead WHERE created_at>='2025-06-23' AND (utm_source IS NOT NULL OR gclid<>'' OR fbclid<>'')) z WHERE rn=1),
  comp AS (   -- COMPLETED SC by COMPLETION week, deduped per patient/completion-week/clinic
    SELECT a.id, RIGHT(p.phone_no,10) ph, loc.city ct, loc.locality lc,
      TO_CHAR(DATE_TRUNC('week', COALESCE(a.actual_start_time,a.start_time,a.created_at) + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') cwk,
      ROW_NUMBER() OVER (PARTITION BY a.patient_id, loc.city, loc.locality,
        DATE_TRUNC('week', COALESCE(a.actual_start_time,a.start_time,a.created_at) + INTERVAL '5 hours 30 minutes') ORDER BY a.id) rn
    FROM allo_consultations.appointments a
    JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
    JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.deleted_at IS NULL AND loc.locality IS NOT NULL AND loc.locality<>''
    JOIN allo_persons.patient p ON p.id=a.patient_id
    WHERE a.deleted_at IS NULL AND a.status='COMPLETED'
      AND COALESCE(a.actual_start_time,a.start_time,a.created_at) >= '{lo}'
      AND COALESCE(a.actual_start_time,a.start_time,a.created_at) < '2026-06-29')
SELECT c.ct, c.lc, c.cwk, {subcase} subcat, {srccase} src,
  COUNT(*) done,
  SUM(CASE WHEN inv.ap_id IS NOT NULL THEN 1 ELSE 0 END) purchased,
  SUM(CASE WHEN inv.ap_id IS NOT NULL THEN COALESCE(inv.amt,0) ELSE 0 END) rev_paise
FROM comp c
  LEFT JOIN etag et ON et.ap_id=c.id LEFT JOIN diag dg ON dg.ap_id=c.id LEFT JOIN inv ON inv.ap_id=c.id
  LEFT JOIN gc ON gc.ph=c.ph LEFT JOIN pc ON pc.ph=c.ph LEFT JOIN u ON u.ph=c.ph
WHERE c.rn=1
GROUP BY 1,2,3,4,5;""".format(lo=LO, subcase=SUBCASE, srccase=PD.SRC_CASE, gmb=PD.GMB_IN, goog=PD.GOOG_IN)

def slugify(loc, city):
    s = lambda x: "".join(ch if ch.isalnum() else "_" for ch in (x or "").strip().lower())
    return s(loc) + "_" + s(city)
CITY_ALIAS = {"bengaluru": "bangalore", "gurgaon": "gurugram"}
def norm_city(c): c = (c or "").strip().lower(); return CITY_ALIAS.get(c, c)

if __name__ == "__main__":
    d = json.load(open(OUT)); clinics = d["clinics"]
    # accumulate per clinic
    B = {}   # slug -> {done:{tot,cat,sub,src,cat_src}, purchased:{...}, rev:{...}}
    def blank():
        return {"done": {"tot": Z(), "cat": {c: Z() for c in CATS}, "sub": {}, "src": {s: Z() for s in SOURCES}, "cat_src": {}},
                "purchased": {"tot": Z(), "cat": {c: Z() for c in CATS}, "sub": {}},
                "rev": {"tot": Z(), "cat": {c: Z() for c in CATS}, "sub": {}}}
    for line in run_sql(SQL):
        r = line.split("\t") if isinstance(line, str) else line
        if len(r) < 8: continue
        ct, lc, cwk, subcat, src, dn, pu, rvp = r[:8]
        if cwk not in idx: continue
        cat = subcat.split("::")[0]
        if cat not in CATS: cat = "Other"
        if src not in SOURCES: src = "untagged"
        slug = slugify(lc, norm_city(ct)); i = idx[cwk]
        try: dn = int(float(dn)); pu = int(float(pu)); rv = round(int(float(rvp)) / 100.0)
        except (ValueError, TypeError): continue
        b = B.setdefault(slug, blank())
        for f, v in (("done", dn), ("purchased", pu), ("rev", rv)):
            b[f]["tot"][i] += v; b[f]["cat"][cat][i] += v
            b[f]["sub"].setdefault(subcat, Z()); b[f]["sub"][subcat][i] += v
        b["done"]["src"][src][i] += dn
        b["done"]["cat_src"].setdefault(cat, {}).setdefault(src, Z())[i] += dn

    matched = 0; drift = []
    for slug, c in clinics.items():
        if slug not in B: continue
        b = B[slug]
        ex_d = sum(c["bottom"]["done"]); ex_p = sum(c["bottom"]["purchased"]); ex_r = sum(c["bottom"]["rev"])
        nd, np_, nr = sum(b["done"]["tot"]), sum(b["purchased"]["tot"]), sum(b["rev"]["tot"])
        # completion-week legitimately differs from booking-week at window edges — allow modest edge drift
        def near(a, e, tol=0.15, fl=6): return abs(a - e) <= max(fl, tol * max(a, e, 1))
        if not (near(nd, ex_d) and near(np_, ex_p) and near(nr, ex_r, 0.18, 4000)):
            drift.append((slug, "%d/%d/%d vs %d/%d/%d" % (nd, np_, nr, ex_d, ex_p, ex_r))); continue
        bot = c["bottom"]
        bot["done"] = b["done"]["tot"]; bot["purchased"] = b["purchased"]["tot"]; bot["rev"] = b["rev"]["tot"]
        for cat in CATS:
            bot.setdefault("by_cat", {}).setdefault(cat, {})
            for f in ("done", "purchased", "rev"): bot["by_cat"][cat][f] = b[f]["cat"][cat]
        for sub in b["done"]["sub"]:
            if sub in bot.get("by_subcat", {}):
                for f in ("done", "purchased", "rev"): bot["by_subcat"][sub][f] = b[f]["sub"].get(sub, Z())
        c["done_by_source"] = b["done"]["src"]
        c["done_cat_source"] = {ct: {s: a for s, a in sr.items() if any(a)} for ct, sr in b["done"]["cat_src"].items() if any(any(a) for a in sr.values())}
        bot["done_by_completion"] = True
        matched += 1
    json.dump(d, open(OUT, "w"), separators=(",", ":"))
    print("rebased %d clinics to completion-week | drift-skipped %d" % (matched, len(drift)))
    for s, why in drift[:15]: print("  DRIFT", s, why)
