#!/usr/bin/env python3
"""Country-level extras for the national funnel:
  _meta.national_channels  — weekly leads by channel (WhatsApp/Meta/Organic/Marketing/Other),
        the pan-India digital channels that aren't city-attributable (so country-only).
  _meta.online_bottom      — the 'Online' consult location's booked/done/purchased/rev by
        STI/SH/MH/Other, for the online vs offline (consult-mode) filter.
Grid-aligned to _meta.weeks (newest-first). Run: AWS_PROFILE=redshift-data python3 scripts/build_country_extra.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import build_source_recon as SR
WEEKS = SR.WEEKS; idx = SR.idx; NW = SR.NW; Z = SR.Z; run_sql = SR.run_sql; LO = SR.LO
ROOT = SR.ROOT; OUT = os.path.join(ROOT, "data_source_recon.json")
CATS = ["STI", "SH", "MH", "Other"]

# ---- national leads + booked by channel (disjoint from clinic-attributed GMB-listing/Google-cpc/Practo) ----
def national_channels():
    sql = ("WITH leads AS (SELECT "
           "  CASE WHEN LOWER(utm_source)='fb' OR COALESCE(fbclid,'')<>'' THEN 'Meta' "          # incl. click-to-WhatsApp ads
           "       WHEN LOWER(utm_source) IN ('gmb','google','practo') THEN 'CLINIC' "
           "       WHEN LOWER(utm_medium) LIKE '%%whatsapp%%' THEN 'WhatsApp' "                  # genuine organic WhatsApp
           "       WHEN LOWER(utm_medium)='assessment' THEN 'Assessment' "
           "       WHEN utm_medium ~ '^[+0-9][0-9]{5,}$' THEN 'OrgCall' "
           "       WHEN LOWER(utm_medium) IN ('healthfeed','blog','article') THEN 'Blog' "
           "       WHEN LOWER(utm_source)='organic' THEN 'Landing' "
           "       WHEN LOWER(utm_source)='marketing' THEN 'Marketing' ELSE 'Other' END channel, "
           "  TO_CHAR(DATE_TRUNC('week', created_at+INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk, RIGHT(phone_no,10) ph "
           "  FROM allo_persons.lead WHERE created_at>='%s' AND created_at<'2026-06-22' AND LENGTH(RIGHT(phone_no,10))=10), "
           "bk AS (SELECT DISTINCT RIGHT(p.phone_no,10) ph FROM allo_consultations.appointments a "
           "  JOIN allo_persons.patient p ON p.id=a.patient_id JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call' "
           "  WHERE a.deleted_at IS NULL AND a.created_at>='2026-02-15') "
           "SELECT leads.channel, leads.wk, COUNT(DISTINCT leads.ph) leads, "
           "  COUNT(DISTINCT CASE WHEN bk.ph IS NOT NULL THEN leads.ph END) booked "
           "FROM leads LEFT JOIN bk ON bk.ph=leads.ph WHERE leads.channel<>'CLINIC' GROUP BY 1,2;" % LO)
    out = {}
    for line in run_sql(sql):
        c = line.split("\t")
        if len(c) < 4 or c[1] not in idx: continue
        out.setdefault(c[0], {"leads": Z(), "booked": Z()})
        try:
            out[c[0]]["leads"][idx[c[1]]] += int(float(c[2])); out[c[0]]["booked"][idx[c[1]]] += int(float(c[3]))
        except ValueError: pass
    return out

# ---- online consult location: booked/done/purchased/rev by category (same logic as bottom_sql, loc='Online') ----
def online_bottom():
    sql = """WITH loc AS (SELECT id FROM allo_health.locations WHERE deleted_at IS NULL AND name='Online'),
  enc_tag AS (SELECT e.appointment_id ap_id,
      CASE WHEN MAX(CASE WHEN et.tag_type='sti' THEN 1 ELSE 0 END)=1 THEN 'STI'
           WHEN MAX(CASE WHEN et.tag_type IN ('ed_plus_pe_plus','ed_plus','pe_plus','nssd') THEN 1 ELSE 0 END)=1 THEN 'SH'
           WHEN MAX(CASE WHEN et.tag_type='others' THEN 1 ELSE 0 END)=1 THEN 'OTH_SH' ELSE 'oth' END tag_cat
    FROM allo_encounters.encounters e
    LEFT JOIN allo_analytics.encounter_tags et ON et.encounter_id=e.id AND et.tag_category='diagnosis' AND et.deleted_at IS NULL
    WHERE e.deleted_at IS NULL GROUP BY 1),
  mh_ap AS (SELECT DISTINCT e.appointment_id ap_id FROM allo_encounters.encounters e
    JOIN allo_observations.diagnoses d ON d.encounter_id=e.id AND d.deleted_at IS NULL
    WHERE e.deleted_at IS NULL AND (d.description LIKE '%(6A%' OR d.description LIKE '%(6B%' OR d.description LIKE '%(6C%'
      OR d.description LIKE '%(6D%' OR d.description LIKE '%(6E%' OR d.description ILIKE '%anxiety%' OR d.description ILIKE '%depress%'
      OR d.description ILIKE '%adhd%' OR d.description ILIKE '%psychosis%' OR d.description ILIKE '%bipolar%' OR d.description ILIKE '%personality%'
      OR d.description ILIKE '%nicotine%' OR d.description ILIKE '%addiction%' OR d.description ILIKE '%adjustment%' OR d.description ILIKE '%ptsd%')),
  ap0 AS (SELECT a.id, a.patient_id, TO_CHAR(DATE_TRUNC('week', a.created_at + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk, a.status
    FROM allo_consultations.appointments a JOIN allo_consultations.types typ ON typ.id=a.type_id AND typ.name='Screening Call'
    JOIN loc ON loc.id=a.location_id WHERE a.created_at >= '2026-03-02' AND a.deleted_at IS NULL),
  ap AS (SELECT id, wk, status FROM (SELECT ap0.*, ROW_NUMBER() OVER (PARTITION BY patient_id, wk
      ORDER BY (CASE WHEN status='COMPLETED' THEN 0 ELSE 1 END), id) rn FROM ap0) z WHERE rn=1),
  inv AS (SELECT e.appointment_id ap_id, SUM(i.amount) amt FROM allo_encounters.encounters e
    JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.deleted_at IS NULL AND i.status='paid' WHERE e.deleted_at IS NULL GROUP BY 1)
  SELECT ap.wk,
    CASE WHEN COALESCE(et.tag_cat,'oth')='STI' THEN 'STI' WHEN COALESCE(et.tag_cat,'oth')='SH' THEN 'SH'
         WHEN mh.ap_id IS NOT NULL THEN 'MH' WHEN COALESCE(et.tag_cat,'oth')='OTH_SH' THEN 'SH' ELSE 'Other' END cat,
    COUNT(*) booked, SUM(CASE WHEN ap.status='COMPLETED' THEN 1 ELSE 0 END) done,
    COUNT(CASE WHEN ap.status='COMPLETED' AND inv.ap_id IS NOT NULL THEN 1 END) purchased,
    SUM(CASE WHEN ap.status='COMPLETED' THEN COALESCE(inv.amt,0) ELSE 0 END) rev_paise
  FROM ap LEFT JOIN enc_tag et ON et.ap_id=ap.id LEFT JOIN mh_ap mh ON mh.ap_id=ap.id LEFT JOIN inv ON inv.ap_id=ap.id
  GROUP BY 1,2;""".replace('%(6','%(6')
    FIELDS = ("booked", "done", "purchased", "rev")
    def blank(): return {k: Z() for k in FIELDS}
    bycat = {c: blank() for c in CATS}; tot = blank()
    for line in run_sql(sql):
        c = line.split("\t")
        if len(c) < 6 or c[0] not in idx: continue
        cat = c[1] if c[1] in CATS else "Other"; i = idx[c[0]]
        try: bk, dn, pu, rp = int(c[2]), int(c[3]), int(c[4]), int(float(c[5]))
        except ValueError: continue
        rev = round(rp / 100.0)
        for tgt in (bycat[cat], tot):
            tgt["booked"][i] += bk; tgt["done"][i] += dn; tgt["purchased"][i] += pu; tgt["rev"][i] += rev
    return {"total": tot, "by_cat": bycat}

# ---- online consults split by normalized patient city (for the City funnel's consult-mode filter) ----
NORM = {'bengaluru':'Bangalore','bangalore':'Bangalore','mumbai':'Mumbai','navi mumbai':'Navi Mumbai','thane':'Mumbai',
  'hyderabad':'Hyderabad','pune':'Pune','chennai':'Chennai','coimbatore':'Coimbatore','ahmedabad':'Ahmedabad',
  'aurangabad':'Aurangabad','bhopal':'Bhopal','gandhinagar':'Gandhinagar','hubli':'Hubli','hubballi':'Hubli',
  'jaipur':'Jaipur','mangaluru':'Mangaluru','mangalore':'Mangaluru','mysuru':'Mysuru','mysore':'Mysuru','nagpur':'Nagpur',
  'nashik':'Nashik','ranchi':'Ranchi','surat':'Surat','visakhapatnam':'Visakhapatnam','vizag':'Visakhapatnam',
  'amravati':'Amravati','vijayawada':'Vijayawada','raipur':'Raipur','tumkur':'Tumkur','tumakuru':'Tumkur','vadodara':'Vadodara'}

def online_bottom_city():
    sql = """WITH loc AS (SELECT id FROM allo_health.locations WHERE deleted_at IS NULL AND name='Online'),
  enc_tag AS (SELECT e.appointment_id ap_id,
      CASE WHEN MAX(CASE WHEN et.tag_type='sti' THEN 1 ELSE 0 END)=1 THEN 'STI'
           WHEN MAX(CASE WHEN et.tag_type IN ('ed_plus_pe_plus','ed_plus','pe_plus','nssd') THEN 1 ELSE 0 END)=1 THEN 'SH'
           WHEN MAX(CASE WHEN et.tag_type='others' THEN 1 ELSE 0 END)=1 THEN 'OTH_SH' ELSE 'oth' END tag_cat
    FROM allo_encounters.encounters e
    LEFT JOIN allo_analytics.encounter_tags et ON et.encounter_id=e.id AND et.tag_category='diagnosis' AND et.deleted_at IS NULL
    WHERE e.deleted_at IS NULL GROUP BY 1),
  mh_ap AS (SELECT DISTINCT e.appointment_id ap_id FROM allo_encounters.encounters e
    JOIN allo_observations.diagnoses d ON d.encounter_id=e.id AND d.deleted_at IS NULL
    WHERE e.deleted_at IS NULL AND (d.description LIKE '%(6A%' OR d.description LIKE '%(6B%' OR d.description LIKE '%(6C%'
      OR d.description LIKE '%(6D%' OR d.description LIKE '%(6E%' OR d.description ILIKE '%anxiety%' OR d.description ILIKE '%depress%'
      OR d.description ILIKE '%adhd%' OR d.description ILIKE '%psychosis%' OR d.description ILIKE '%bipolar%' OR d.description ILIKE '%personality%'
      OR d.description ILIKE '%nicotine%' OR d.description ILIKE '%addiction%' OR d.description ILIKE '%adjustment%' OR d.description ILIKE '%ptsd%')),
  ap0 AS (SELECT a.id, a.patient_id, TO_CHAR(DATE_TRUNC('week', a.created_at + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk, a.status
    FROM allo_consultations.appointments a JOIN allo_consultations.types typ ON typ.id=a.type_id AND typ.name='Screening Call'
    JOIN loc ON loc.id=a.location_id WHERE a.created_at >= '2026-03-02' AND a.deleted_at IS NULL),
  ap AS (SELECT id, patient_id, wk, status FROM (SELECT ap0.*, ROW_NUMBER() OVER (PARTITION BY patient_id, wk
      ORDER BY (CASE WHEN status='COMPLETED' THEN 0 ELSE 1 END), id) rn FROM ap0) z WHERE rn=1),
  inv AS (SELECT e.appointment_id ap_id, SUM(i.amount) amt FROM allo_encounters.encounters e
    JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.deleted_at IS NULL AND i.status='paid' WHERE e.deleted_at IS NULL GROUP BY 1)
  SELECT LOWER(TRIM(p.city)) pcity, ap.wk,
    CASE WHEN COALESCE(et.tag_cat,'oth')='STI' THEN 'STI' WHEN COALESCE(et.tag_cat,'oth')='SH' THEN 'SH'
         WHEN mh.ap_id IS NOT NULL THEN 'MH' WHEN COALESCE(et.tag_cat,'oth')='OTH_SH' THEN 'SH' ELSE 'Other' END cat,
    COUNT(*) booked, SUM(CASE WHEN ap.status='COMPLETED' THEN 1 ELSE 0 END) done,
    COUNT(CASE WHEN ap.status='COMPLETED' AND inv.ap_id IS NOT NULL THEN 1 END) purchased,
    SUM(CASE WHEN ap.status='COMPLETED' THEN COALESCE(inv.amt,0) ELSE 0 END) rev_paise
  FROM ap JOIN allo_persons.patient p ON p.id=ap.patient_id
  LEFT JOIN enc_tag et ON et.ap_id=ap.id LEFT JOIN mh_ap mh ON mh.ap_id=ap.id LEFT JOIN inv ON inv.ap_id=ap.id
  GROUP BY 1,2,3;"""
    FIELDS = ("booked", "done", "purchased", "rev")
    out = {}
    for line in run_sql(sql):
        c = line.split("\t")
        if len(c) < 7 or c[1] not in idx: continue
        city = NORM.get((c[0] or "").strip())
        if not city: continue
        cat = c[2] if c[2] in CATS else "Other"; i = idx[c[1]]
        d = out.setdefault(city, {"total": {k: Z() for k in FIELDS}, "by_cat": {ct: {k: Z() for k in FIELDS} for ct in CATS}})
        try: bk, dn, pu, rp = int(c[3]), int(c[4]), int(c[5]), int(float(c[6]))
        except ValueError: continue
        rev = round(rp / 100.0)
        for tgt in (d["by_cat"][cat], d["total"]):
            tgt["booked"][i] += bk; tgt["done"][i] += dn; tgt["purchased"][i] += pu; tgt["rev"][i] += rev
    return out

# ---- online bookings split by lead channel (phone → patient's latest lead source) ----
SRC_CHANS = ["Google", "GMB", "Practo", "Meta", "Organic", "Direct"]
def online_src():
    sql = """WITH onl AS (SELECT id FROM allo_health.locations WHERE deleted_at IS NULL AND name='Online'),
  ap0 AS (SELECT a.id, a.patient_id, TO_CHAR(DATE_TRUNC('week', a.created_at + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk
    FROM allo_consultations.appointments a JOIN allo_consultations.types typ ON typ.id=a.type_id AND typ.name='Screening Call'
    JOIN onl ON onl.id=a.location_id WHERE a.created_at>='2026-03-02' AND a.deleted_at IS NULL),
  ap AS (SELECT id, patient_id, wk FROM (SELECT ap0.*, ROW_NUMBER() OVER (PARTITION BY patient_id, wk ORDER BY id) rn FROM ap0) z WHERE rn=1),
  lead_ch AS (SELECT RIGHT(phone_no,10) ph,
      CASE WHEN LOWER(utm_source)='fb' OR COALESCE(fbclid,'')<>'' THEN 'Meta'
           WHEN LOWER(utm_source)='google' THEN 'Google' WHEN LOWER(utm_source)='gmb' THEN 'GMB'
           WHEN LOWER(utm_source)='practo' THEN 'Practo'
           WHEN LOWER(utm_source)='organic' OR LOWER(utm_medium) LIKE '%whatsapp%' THEN 'Organic' ELSE 'Other' END ch,
      ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY created_at DESC) rn
    FROM allo_persons.lead WHERE LENGTH(RIGHT(phone_no,10))=10)
  SELECT COALESCE(lc.ch,'Direct') channel, ap.wk, LOWER(TRIM(p.city)) pcity, COUNT(*) n
  FROM ap JOIN allo_persons.patient p ON p.id=ap.patient_id
  LEFT JOIN lead_ch lc ON lc.ph=RIGHT(p.phone_no,10) AND lc.rn=1
  GROUP BY 1,2,3;"""
    nat = {c: Z() for c in SRC_CHANS}; cty = {}
    for line in run_sql(sql):
        c = line.split("\t")
        if len(c) < 4 or c[1] not in idx: continue
        ch = c[0] if c[0] in SRC_CHANS else "Direct"   # 'Other' (unknown source) + no-lead → Direct
        i = idx[c[1]]
        try: v = int(float(c[3]))
        except ValueError: continue
        nat[ch][i] += v
        city = NORM.get((c[2] or "").strip())
        if city:
            cty.setdefault(city, {k: Z() for k in SRC_CHANS})
            cty[city][ch][i] += v
    return {"national": nat, "city": cty}

# ---- online revenue by line-item type (national + by patient city) ----
RTYPES = ["drug", "lab", "consultation", "other"]
def online_rev_type():
    sql = """WITH onl AS (SELECT id FROM allo_health.locations WHERE deleted_at IS NULL AND name='Online'),
  ap0 AS (SELECT a.id, a.patient_id, TO_CHAR(DATE_TRUNC('week', a.created_at + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk
    FROM allo_consultations.appointments a JOIN allo_consultations.types typ ON typ.id=a.type_id AND typ.name='Screening Call'
    JOIN onl ON onl.id=a.location_id WHERE a.created_at>='2026-03-02' AND a.deleted_at IS NULL AND a.status='COMPLETED'),
  ap AS (SELECT id, patient_id, wk FROM (SELECT ap0.*, ROW_NUMBER() OVER (PARTITION BY patient_id, wk ORDER BY id) rn FROM ap0) z WHERE rn=1)
  SELECT LOWER(TRIM(p.city)) pcity, ap.wk, LOWER(ii."type") itype, SUM(ii.payable_amount) amt
  FROM ap JOIN allo_persons.patient p ON p.id=ap.patient_id
  JOIN allo_encounters.encounters e ON e.appointment_id=ap.id AND e.deleted_at IS NULL
  JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.status='paid' AND i.deleted_at IS NULL
  JOIN allo_billing.invoice_items ii ON ii.invoice_id=i.id AND ii.deleted_at IS NULL
  GROUP BY 1,2,3;"""
    nat = {t: Z() for t in RTYPES}; cty = {}
    for line in run_sql(sql):
        c = line.split("\t")
        if len(c) < 4 or c[1] not in idx: continue
        t = c[2] if c[2] in RTYPES else "other"; i = idx[c[1]]
        try: v = round(int(float(c[3])) / 100.0)
        except ValueError: continue
        nat[t][i] += v
        city = NORM.get((c[0] or "").strip())
        if city:
            cty.setdefault(city, {x: Z() for x in RTYPES}); cty[city][t][i] += v
    return nat, cty

if __name__ == "__main__":
    d = json.load(open(OUT))
    print("pulling national channels (leads + booked)…", flush=True)
    nc = national_channels()
    print(" ", {k: (sum(v["leads"]), sum(v["booked"])) for k, v in nc.items()}, flush=True)
    print("pulling online bottom…", flush=True)
    ob = online_bottom()
    print("  online done/wk:", ob["total"]["done"][:4], flush=True)
    print("pulling online bottom by city…", flush=True)
    obc = online_bottom_city()
    print("  online cities:", {k: sum(v["total"]["done"]) for k, v in sorted(obc.items(), key=lambda x: -sum(x[1]["total"]["done"]))[:6]}, flush=True)
    print("pulling online bookings by source…", flush=True)
    osrc = online_src()
    print("  online src (national):", {k: sum(v) for k, v in osrc["national"].items()}, flush=True)
    print("pulling online revenue by type…", flush=True)
    ort_nat, ort_cty = online_rev_type()
    print("  online rev_type:", {k: sum(v) for k, v in ort_nat.items()}, flush=True)
    ob["rev_type"] = ort_nat
    for city, rt in ort_cty.items():
        if city in obc: obc[city]["rev_type"] = rt
    d["_meta"]["national_channels"] = nc
    d["_meta"]["online_bottom"] = ob
    d["_meta"]["online_bottom_city"] = obc
    d["_meta"]["online_src"] = osrc["national"]
    d["_meta"]["online_src_city"] = osrc["city"]
    json.dump(d, open(OUT, "w"), separators=(",", ":"))
    print("saved.")
