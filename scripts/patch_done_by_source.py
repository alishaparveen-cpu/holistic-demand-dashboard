#!/usr/bin/env python3
"""Network-wide DONE-by-source patch for data_source_recon.json (all ~78 clinics).
The source-recon builder was narrowed to 7 MH clinics, so it can't regenerate the full
file. This standalone script computes, for EVERY clinic, weekly bookings + done split by
source (same priority as the recon builder: call-category > UTM), in ONE query, and patches
`done_by_source` into each clinic. It does NOT touch the displayed `by_source` (booked); it
also prints how closely the freshly-recomputed booked matches the legacy by_source so we know
the reconciliation quality.
Run: AWS_PROFILE=redshift-data python3 scripts/patch_done_by_source.py
"""
import os, sys, json, subprocess, datetime
import openpyxl
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
def run_sql(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("query failed: " + (p.stderr or "")[:600] + "\n"); sys.exit(1)
    return [l.split("\t") for l in p.stdout.strip().splitlines() if l.strip()]

# ---- source-recon window + sources ----
data = json.load(open(os.path.join(ROOT, "data_source_recon.json")))
WEEKS = data["_meta"]["weeks"]; idx = {w: i for i, w in enumerate(WEEKS)}; NW = len(WEEKS); LO = min(WEEKS)  # weeks are stored newest-first
SOURCES = ["gmb_call","gmb_web","gmb_wa","gpaid_call","gpaid_web","practo","meta","organic","untagged"]
def Z(): return [0]*NW

# ---- GMB / Google call numbers from the exophone sheet (network-wide, all clinics) ----
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

# ---- one network-wide query: bookings + done by (city, locality, week, source) ----
SQL = """WITH bk0 AS (
  SELECT a.patient_id, RIGHT(p.phone_no,10) ph, a.status, loc.city ct, loc.locality lc,
    TO_CHAR(DATE_TRUNC('week', a.created_at+INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk,
    ROW_NUMBER() OVER (PARTITION BY a.patient_id, loc.city, loc.locality,
       TO_CHAR(DATE_TRUNC('week',a.created_at+INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD')
       ORDER BY (CASE WHEN a.status='COMPLETED' THEN 0 ELSE 1 END), a.created_at) rn  -- COMPLETED-preferred (matches the Done-row dedup)
  FROM allo_consultations.appointments a
  JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.deleted_at IS NULL AND loc.locality IS NOT NULL AND loc.locality<>''
  JOIN allo_persons.patient p ON p.id=a.patient_id
  JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
  WHERE a.deleted_at IS NULL AND a.created_at >= '{lo}' AND a.created_at < '2026-06-29'),
 bk AS (SELECT patient_id, ph, status, ct, lc, wk FROM bk0 WHERE rn=1),
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
GROUP BY 1,2,3,4;""".format(lo=LO, gmb=gmb_in, goog=goog_in)

def slugify(loc, city):
    s = lambda x: "".join(ch if ch.isalnum() else "_" for ch in (x or "").strip().lower())
    return s(loc) + "_" + s(city)

# city aliases so sheet/db city names resolve to the data_source_recon slugs
CITY_ALIAS = {"bengaluru": "bangalore", "gurgaon": "gurugram"}
def norm_city(c):
    c = (c or "").strip().lower(); return CITY_ALIAS.get(c, c)

# build slug -> {src: booked[], done[]}
clinics = data["clinics"]
# map normalized (loc,city) slug -> existing data key
key_by_slug = {}
for k in clinics:
    key_by_slug[k] = k                       # exact
# also index by loc-prefix for fuzzy city match
booked = {}; done = {}
for row in run_sql(SQL):
    if len(row) < 6: continue
    ct, lc, wk, src, n_s, dn_s = row[0], row[1], row[2], row[3], row[4], row[5]
    if wk not in idx or src not in SOURCES: continue
    slug = slugify(lc, norm_city(ct))
    i = idx[wk]
    try: n = int(float(n_s)); dn = int(float(dn_s))
    except ValueError: continue
    booked.setdefault(slug, {s: Z() for s in SOURCES}); done.setdefault(slug, {s: Z() for s in SOURCES})
    booked[slug][src][i] += n; done[slug][src][i] += dn

# attach done_by_source; report reconciliation of recomputed booked vs legacy by_source
matched = 0; unmatched = []
recon_tot = 0; legacy_tot = 0
maxdelta = 0; big = []
for slug, c in clinics.items():
    if slug in done:
        rb = sum(sum(booked[slug][s]) for s in SOURCES)
        lb = sum(sum(c["by_source"].get(s, Z())) for s in SOURCES)
        # replace by_source + done_by_source with the ONE consistent attribution -> done <= booked always, no clamp
        c["by_source"] = booked[slug]
        c["done_by_source"] = done[slug]
        matched += 1; recon_tot += rb; legacy_tot += lb
        d = abs(rb - lb); maxdelta = max(maxdelta, d)
        if lb and d / lb > 0.05: big.append((slug, lb, rb))
    else:
        c["done_by_source"] = {s: Z() for s in SOURCES}
        unmatched.append(slug)
print("max per-clinic booked delta (recompute vs legacy):", maxdelta)
if big: print("  clinics with >5%% booked delta (%d):" % len(big), big[:10])

json.dump(data, open(os.path.join(ROOT, "data_source_recon.json"), "w"), separators=(",", ":"))
print("clinics patched with done_by_source: %d / %d" % (matched, len(clinics)))
if unmatched: print("  unmatched (no Redshift booking match, done=0):", unmatched[:15], "..." if len(unmatched) > 15 else "")
print("recomputed booked total %d vs legacy by_source total %d  (%.1f%% of legacy)" %
      (recon_tot, legacy_tot, 100.0*recon_tot/legacy_tot if legacy_tot else 0))
