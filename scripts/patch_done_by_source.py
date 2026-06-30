#!/usr/bin/env python3
"""Network-wide DONE-by-source (+ category x source) patch for data_source_recon.json.
The source-recon builder was narrowed to 7 MH clinics, so it can't regenerate the full
78-clinic file. This standalone script, in ONE query, computes per clinic/week:
  - bookings + done by SOURCE (priority: call-category > UTM)  -> by_source, done_by_source
  - done by CATEGORY x SOURCE (STI/SH/MH/Other x source)        -> done_cat_source (sparse)
Category logic mirrors build_mh_funnels.bottom_sql (STI/SH via encounter_tags, MH via ICD-11).
Replaces by_source/done_by_source in place (matches legacy to within ~1/clinic); adds
done_cat_source. Prints reconciliation vs legacy by_source and vs bottom.done / by_cat done.
Run: AWS_PROFILE=redshift-data python3 scripts/patch_done_by_source.py
"""
import os, sys, json, subprocess
import openpyxl
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
def run_sql(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("query failed: " + (p.stderr or "")[:600] + "\n"); sys.exit(1)
    return [l.split("\t") for l in p.stdout.strip().splitlines() if l.strip()]

data = json.load(open(os.path.join(ROOT, "data_source_recon.json")))
WEEKS = data["_meta"]["weeks"]; idx = {w: i for i, w in enumerate(WEEKS)}; NW = len(WEEKS); LO = min(WEEKS)
SOURCES = ["gmb_call","gmb_web","gmb_wa","gpaid_call","gpaid_web","practo","meta","organic","untagged"]
CATS = ["STI", "SH", "MH", "Other"]
def Z(): return [0]*NW

wb = openpyxl.load_workbook(os.path.expanduser("~/Downloads/exophone_categorisation.xlsx"), read_only=True)
ws = wb["All Numbers"]; xr = list(ws.iter_rows(values_only=True)); xh = {c: i for i, c in enumerate(xr[0])}
GMB_NUMS, GOOG_NUMS = set(), set()
for r in xr[1:]:
    num = str(r[xh["Exotel Number"]] or "").strip()[-10:]
    if not num: continue
    cat = (r[xh["Category"]] or "").strip().lower()
    if cat == "gmb": GMB_NUMS.add(num)
    elif cat == "google": GOOG_NUMS.add(num)
gmb_in = "','".join(sorted(GMB_NUMS)); goog_in = "','".join(sorted(GOOG_NUMS))

SQL = """WITH bk0 AS (
  SELECT a.id apid, a.patient_id, RIGHT(p.phone_no,10) ph, a.status, loc.city ct, loc.locality lc,
    TO_CHAR(DATE_TRUNC('week', a.created_at+INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk,
    ROW_NUMBER() OVER (PARTITION BY a.patient_id, loc.city, loc.locality,
       TO_CHAR(DATE_TRUNC('week',a.created_at+INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD')
       ORDER BY (CASE WHEN a.status='COMPLETED' THEN 0 ELSE 1 END), a.id) rn  -- COMPLETED-preferred (matches Done dedup)
  FROM allo_consultations.appointments a
  JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.deleted_at IS NULL AND loc.locality IS NOT NULL AND loc.locality<>''
  JOIN allo_persons.patient p ON p.id=a.patient_id
  JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
  WHERE a.deleted_at IS NULL AND a.created_at >= '{lo}' AND a.created_at < '2026-06-29'),
 bk AS (SELECT apid, patient_id, ph, status, ct, lc, wk FROM bk0 WHERE rn=1),
 enc_tag AS (
   SELECT e.appointment_id ap_id,
     CASE WHEN MAX(CASE WHEN et.tag_type='sti' THEN 1 ELSE 0 END)=1 THEN 'STI'
          WHEN MAX(CASE WHEN et.tag_type IN ('ed_plus_pe_plus','ed_plus','pe_plus','nssd') THEN 1 ELSE 0 END)=1 THEN 'SH'
          WHEN MAX(CASE WHEN et.tag_type='others' THEN 1 ELSE 0 END)=1 THEN 'OTH_SH'
          ELSE 'oth' END tag_cat
   FROM allo_encounters.encounters e
   LEFT JOIN allo_analytics.encounter_tags et ON et.encounter_id=e.id AND et.tag_category='diagnosis' AND et.deleted_at IS NULL
   WHERE e.deleted_at IS NULL GROUP BY 1),
 mh_ap AS (
   SELECT DISTINCT e.appointment_id ap_id FROM allo_encounters.encounters e
   JOIN allo_observations.diagnoses d ON d.encounter_id=e.id AND d.deleted_at IS NULL
   WHERE e.deleted_at IS NULL AND (d.description LIKE '%(6A%' OR d.description LIKE '%(6B%' OR d.description LIKE '%(6C%'
     OR d.description LIKE '%(6D%' OR d.description LIKE '%(6E%' OR d.description ILIKE '%anxiety%' OR d.description ILIKE '%depress%'
     OR d.description ILIKE '%adhd%' OR d.description ILIKE '%psychosis%' OR d.description ILIKE '%bipolar%' OR d.description ILIKE '%personality%'
     OR d.description ILIKE '%nicotine%' OR d.description ILIKE '%addiction%' OR d.description ILIKE '%adjustment%' OR d.description ILIKE '%ptsd%')),
 gc AS (SELECT DISTINCT RIGHT("from",10) ph FROM allo_vendors.exotel_calls
        WHERE RIGHT(exotel_number,10) IN ('{gmb}') AND routed_to='lead_to_call' AND direction='inbound' AND start_time>='2025-06-23'),
 pc AS (SELECT DISTINCT RIGHT("from",10) ph FROM allo_vendors.exotel_calls
        WHERE RIGHT(exotel_number,10) IN ('{goog}') AND routed_to='lead_to_call' AND direction='inbound' AND start_time>='2025-06-23'),
 u AS (SELECT ph,us,um,g,f FROM (
    SELECT RIGHT(phone_no,10) ph, LOWER(COALESCE(utm_source,'')) us, LOWER(COALESCE(utm_medium,'')) um,
      CASE WHEN gclid<>'' THEN 1 ELSE 0 END g, CASE WHEN fbclid<>'' THEN 1 ELSE 0 END f,
      ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY created_at DESC) rn
    FROM allo_persons.lead WHERE created_at>='2025-06-23' AND (utm_source IS NOT NULL OR gclid<>'' OR fbclid<>'')) z WHERE rn=1)
SELECT bk.ct, bk.lc, bk.wk,
  CASE WHEN COALESCE(et.tag_cat,'oth')='STI' THEN 'STI' WHEN COALESCE(et.tag_cat,'oth')='SH' THEN 'SH'
       WHEN mh.ap_id IS NOT NULL THEN 'MH'
       WHEN COALESCE(et.tag_cat,'oth')='OTH_SH' THEN 'SH' ELSE 'Other' END cat,
  CASE
    WHEN gc.ph IS NOT NULL THEN 'gmb_call'
    WHEN u.us='gmb' AND u.um='whatsapp' THEN 'gmb_wa'
    WHEN u.us='gmb' THEN 'gmb_web'
    WHEN pc.ph IS NOT NULL THEN 'gpaid_call'
    WHEN u.g=1 OR u.us='google' THEN 'gpaid_web'
    WHEN u.us='practo' THEN 'practo'
    WHEN u.f=1 OR u.us IN ('fb','facebook','instagram','ig') THEN 'meta'
    WHEN u.us='organic' THEN 'organic'
    ELSE 'untagged' END src,
  COUNT(*) n, SUM(CASE WHEN bk.status='COMPLETED' THEN 1 ELSE 0 END) dn
FROM bk LEFT JOIN gc ON gc.ph=bk.ph LEFT JOIN pc ON pc.ph=bk.ph LEFT JOIN u ON u.ph=bk.ph
  LEFT JOIN enc_tag et ON et.ap_id=bk.apid LEFT JOIN mh_ap mh ON mh.ap_id=bk.apid
GROUP BY 1,2,3,4,5;""".format(lo=LO, gmb=gmb_in, goog=goog_in)

def slugify(loc, city):
    s = lambda x: "".join(ch if ch.isalnum() else "_" for ch in (x or "").strip().lower())
    return s(loc) + "_" + s(city)
CITY_ALIAS = {"bengaluru": "bangalore", "gurgaon": "gurugram"}
def norm_city(c):
    c = (c or "").strip().lower(); return CITY_ALIAS.get(c, c)

clinics = data["clinics"]
booked, done, cat_src, cat_src_bk = {}, {}, {}, {}
for row in run_sql(SQL):
    if len(row) < 7: continue
    ct, lc, wk, cat, src, n_s, dn_s = row[:7]
    if wk not in idx or src not in SOURCES: continue
    if cat not in CATS: cat = "Other"
    slug = slugify(lc, norm_city(ct)); i = idx[wk]
    try: n = int(float(n_s)); dn = int(float(dn_s))
    except ValueError: continue
    booked.setdefault(slug, {s: Z() for s in SOURCES}); done.setdefault(slug, {s: Z() for s in SOURCES})
    cat_src.setdefault(slug, {}); cat_src_bk.setdefault(slug, {})
    booked[slug][src][i] += n; done[slug][src][i] += dn
    if dn:
        cat_src[slug].setdefault(cat, {}).setdefault(src, Z())[i] += dn
    if n:
        cat_src_bk[slug].setdefault(cat, {}).setdefault(src, Z())[i] += n

matched = 0; unmatched = []; maxdelta = 0
for slug, c in clinics.items():
    if slug in done:
        rb = sum(sum(booked[slug][s]) for s in SOURCES); lb = sum(sum(c["by_source"].get(s, Z())) for s in SOURCES)
        c["by_source"] = booked[slug]; c["done_by_source"] = done[slug]
        # sparse cat -> src -> weekly (drop all-zero series)
        def sparse(d): return {cat: {s: arr for s, arr in srcs.items() if any(arr)} for cat, srcs in d.items() if any(any(a) for a in srcs.values())}
        c["done_cat_source"] = sparse(cat_src.get(slug, {}))
        c["booked_cat_source"] = sparse(cat_src_bk.get(slug, {}))
        matched += 1; maxdelta = max(maxdelta, abs(rb - lb))
    else:
        c["done_by_source"] = {s: Z() for s in SOURCES}; c["done_cat_source"] = {}; c["booked_cat_source"] = {}
        unmatched.append(slug)

json.dump(data, open(os.path.join(ROOT, "data_source_recon.json"), "w"), separators=(",", ":"))
# reconciliation
tb = sum(sum(sum(c["by_source"][s]) for s in SOURCES) for c in clinics.values())
td = sum(sum(sum(c["done_by_source"][s]) for s in SOURCES) for c in clinics.values())
tbo = sum(sum(c["bottom"]["done"]) for c in clinics.values())
# category x source done summed over source vs bottom.by_cat done
tcs = sum(sum(sum(arr) for arr in srcs.values()) for c in clinics.values() for srcs in c["done_cat_source"].values())
print("patched %d/%d clinics | max booked delta %d" % (matched, len(clinics), maxdelta))
print("by_source booked=%d | done_by_source=%d (bottom.done=%d, %.0f%%) | done_cat_source total=%d" %
      (tb, td, tbo, 100*td/tbo if tbo else 0, tcs))
if unmatched: print("unmatched (empty):", unmatched[:12])
