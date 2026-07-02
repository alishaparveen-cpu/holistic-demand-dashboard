#!/usr/bin/env python3
"""Daily version of the MASTER sheet — per clinic × DAY for the last 42 days (6 weeks), same schema
as data_source_recon.json so master.html's engine renders it unchanged (just day columns).

Writes data_daily_master.json (NOT data_daily.json — that belongs to Quick View) with
_meta.weeks = 42 day-dates (newest first) and, per clinic:
  bottom.{booked,done,purchased,rev} + bottom.by_cat[cat].{done,purchased,rev}
  booked_by_source / done_by_source  (channel keys, service-day / completion-day)
  by_doctor[doctor].{booked,done,purchased,rev}
Plus _meta.master_leads (daily by source). Scaffolding (display/city_tier/clinic_age/clinics/sources)
is copied from data_source_recon.json so the top filters behave identically.

booked = SC by SERVICE day (start_time), done/purchased/rev = COMPLETED SC by COMPLETION day.
Run: AWS_PROFILE=redshift-data python3 scripts/build_daily_master.py
"""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(__file__))
import patch_subcat as PS
import patch_demand_first as PD
ROOT = PS.ROOT; run_sql = PS.run_sql; SUBCASE = PS.SUBCASE
SRC_CASE = PD.SRC_CASE; GMB_IN = PD.GMB_IN; GOOG_IN = PD.GOOG_IN; SOURCES = PD.SOURCES
CATS = ["STI", "SH", "MH", "Other"]

END = datetime.date(2026, 7, 1)     # last full day (currentDate is 2026-07-02)
NDAYS = 42
DAYS = [(END - datetime.timedelta(days=i)).isoformat() for i in range(NDAYS)]   # newest first
idx = {d: i for i, d in enumerate(DAYS)}
LO = DAYS[-1]
Z = lambda: [0] * NDAYS

BOOK_SQL = """WITH sc AS (
  SELECT a.id, a.patient_id, RIGHT(p.phone_no,10) ph, loc.city ct, loc.locality lc, pro.name doctor, a.status,
    DATE(a.start_time + INTERVAL '5 hours 30 minutes') dt
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.deleted_at IS NULL AND loc.locality IS NOT NULL AND loc.locality<>''
  JOIN allo_persons.patient p ON p.id=a.patient_id
  JOIN allo_persons.providers pro ON pro.id=a.provider_id AND pro.deleted_at IS NULL
  WHERE a.deleted_at IS NULL AND DATE(a.start_time + INTERVAL '5 hours 30 minutes') BETWEEN '{lo}' AND '{end}'),
 dd AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY patient_id,ct,lc,dt ORDER BY (CASE WHEN status='COMPLETED' THEN 0 ELSE 1 END), id) rn FROM sc),
 gc AS (SELECT DISTINCT RIGHT("from",10) ph FROM allo_vendors.exotel_calls WHERE RIGHT(exotel_number,10) IN ('{gmb}') AND routed_to='lead_to_call' AND direction='inbound' AND start_time>='2025-06-23'),
 pc AS (SELECT DISTINCT RIGHT("from",10) ph FROM allo_vendors.exotel_calls WHERE RIGHT(exotel_number,10) IN ('{goog}') AND routed_to='lead_to_call' AND direction='inbound' AND start_time>='2025-06-23'),
 u AS (SELECT ph,us,um,g,f FROM (SELECT RIGHT(phone_no,10) ph, LOWER(COALESCE(utm_source,'')) us, LOWER(COALESCE(utm_medium,'')) um,
       CASE WHEN gclid<>'' THEN 1 ELSE 0 END g, CASE WHEN fbclid<>'' THEN 1 ELSE 0 END f,
       ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY created_at DESC) rn
     FROM allo_persons.lead WHERE created_at>='2025-06-23' AND (utm_source IS NOT NULL OR gclid<>'' OR fbclid<>'')) z WHERE rn=1)
SELECT dd.ct, dd.lc, TO_CHAR(dd.dt,'YYYY-MM-DD') d, dd.doctor, {srccase} src, COUNT(*) booked
FROM dd LEFT JOIN gc ON gc.ph=dd.ph LEFT JOIN pc ON pc.ph=dd.ph LEFT JOIN u ON u.ph=dd.ph
WHERE dd.rn=1 GROUP BY 1,2,3,4,5;""".format(lo=LO, end=END.isoformat(), gmb=GMB_IN, goog=GOOG_IN, srccase=SRC_CASE)

DONE_SQL = """WITH etag AS (SELECT e.appointment_id ap_id,
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
  gc AS (SELECT DISTINCT RIGHT("from",10) ph FROM allo_vendors.exotel_calls WHERE RIGHT(exotel_number,10) IN ('{gmb}') AND routed_to='lead_to_call' AND direction='inbound' AND start_time>='2025-06-23'),
  pc AS (SELECT DISTINCT RIGHT("from",10) ph FROM allo_vendors.exotel_calls WHERE RIGHT(exotel_number,10) IN ('{goog}') AND routed_to='lead_to_call' AND direction='inbound' AND start_time>='2025-06-23'),
  u AS (SELECT ph,us,um,g,f FROM (SELECT RIGHT(phone_no,10) ph, LOWER(COALESCE(utm_source,'')) us, LOWER(COALESCE(utm_medium,'')) um,
       CASE WHEN gclid<>'' THEN 1 ELSE 0 END g, CASE WHEN fbclid<>'' THEN 1 ELSE 0 END f,
       ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY created_at DESC) rn
     FROM allo_persons.lead WHERE created_at>='2025-06-23' AND (utm_source IS NOT NULL OR gclid<>'' OR fbclid<>'')) z WHERE rn=1),
  comp AS (SELECT a.id, RIGHT(p.phone_no,10) ph, pro.name doctor, loc.city ct, loc.locality lc,
      TO_CHAR(DATE(COALESCE(a.actual_start_time,a.start_time,a.created_at) + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') d,
      ROW_NUMBER() OVER (PARTITION BY a.patient_id, loc.city, loc.locality,
        DATE(COALESCE(a.actual_start_time,a.start_time,a.created_at) + INTERVAL '5 hours 30 minutes') ORDER BY a.id) rn
    FROM allo_consultations.appointments a
    JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
    JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.deleted_at IS NULL AND loc.locality IS NOT NULL AND loc.locality<>''
    JOIN allo_persons.patient p ON p.id=a.patient_id
    JOIN allo_persons.providers pro ON pro.id=a.provider_id AND pro.deleted_at IS NULL
    WHERE a.deleted_at IS NULL AND a.status='COMPLETED'
      AND DATE(COALESCE(a.actual_start_time,a.start_time,a.created_at) + INTERVAL '5 hours 30 minutes') BETWEEN '{lo}' AND '{end}')
SELECT c.ct, c.lc, c.d, c.doctor, SPLIT_PART({subcase},'::',1) cat, {srccase} src,
  COUNT(*) done,
  SUM(CASE WHEN inv.ap_id IS NOT NULL THEN 1 ELSE 0 END) purchased,
  SUM(CASE WHEN inv.ap_id IS NOT NULL THEN COALESCE(inv.amt,0) ELSE 0 END) rev_paise
FROM comp c LEFT JOIN etag et ON et.ap_id=c.id LEFT JOIN diag dg ON dg.ap_id=c.id LEFT JOIN inv ON inv.ap_id=c.id
  LEFT JOIN gc ON gc.ph=c.ph LEFT JOIN pc ON pc.ph=c.ph LEFT JOIN u ON u.ph=c.ph
WHERE c.rn=1 GROUP BY 1,2,3,4,5,6;""".format(lo=LO, end=END.isoformat(), gmb=GMB_IN, goog=GOOG_IN, subcase=SUBCASE, srccase=SRC_CASE)

LEADS_SQL = """WITH ld AS (
  SELECT phone_no1 ph, source, organic_l2, created_on_date::date dd,
    ROW_NUMBER() OVER (PARTITION BY phone_no1 ORDER BY created_on_date) rn
  FROM production.public.main_source_wise_leads WHERE created_on_date >= '2023-01-01'),
 fl AS (SELECT ph, source, organic_l2, DATE(dd + INTERVAL '5 hours 30 minutes') fd FROM ld WHERE rn=1),
 fb AS (SELECT phone_no1 ph, MIN(call_booking_ts) fbt FROM production.public.main_source_wise_leads WHERE call_booking_ts IS NOT NULL GROUP BY 1),
 utm AS (SELECT RIGHT(phone_no,10) ph10,
    MAX(CASE WHEN utm_source ILIKE 'practo%' THEN 4 WHEN utm_source ILIKE 'gmb%' THEN 3 WHEN utm_source ILIKE 'google%' THEN 2 WHEN utm_source ILIKE 'organic%' THEN 1 ELSE 0 END) pr
    FROM allo_prod.allo_persons.lead WHERE phone_no IS NOT NULL GROUP BY 1)
SELECT TO_CHAR(fl.fd,'YYYY-MM-DD') d,
  CASE WHEN fl.source='Google' THEN 'Google Ads'
       WHEN fl.source IN ('Fb','Facebook','Instagram','Ig','Meta') THEN 'Meta'
       WHEN fl.source='Organic' AND fl.organic_l2 IN ('Google Listing','PC-Inbound') THEN 'GMB'
       WHEN fl.source='Organic' AND fl.organic_l2='WA-Inbound' THEN 'WhatsApp'
       WHEN fl.source='Organic' AND fl.organic_l2='Walk In' THEN 'Walk-in'
       WHEN fl.source='Organic' AND fl.organic_l2 IN ('Clinic Page','Doctor','Doctor Pages','Sexologist','Treatment Page','Login Page','Healthfeed','Webbot','Homepage','Home Page','Blog','STD Testing','Assessment Page','Evaluation Page','ED Page','PE Page','Author Profile Page') THEN 'Website'
       WHEN fl.source='Organic' THEN 'Organic (untagged)'
       WHEN fl.source='Justdial' THEN 'JustDial'
       WHEN fl.source ILIKE 'Practo%' THEN 'Practo'
       WHEN fl.source='Newspaper' THEN 'Newspaper'
       WHEN fl.source='Youtube' THEN 'YouTube'
       WHEN u.pr=4 THEN 'Practo' WHEN u.pr=3 THEN 'GMB' WHEN u.pr=2 THEN 'Google Ads' WHEN u.pr=1 THEN 'Organic (untagged)'
       ELSE 'Other' END src,
  COUNT(*) new_leads,
  SUM(CASE WHEN fb.fbt IS NOT NULL AND DATE(fb.fbt+INTERVAL '5 hours 30 minutes')=fl.fd THEN 1 ELSE 0 END) booked_same,
  SUM(CASE WHEN fb.fbt IS NOT NULL AND DATE(fb.fbt+INTERVAL '5 hours 30 minutes')>fl.fd THEN 1 ELSE 0 END) booked_later,
  SUM(CASE WHEN fb.fbt IS NULL THEN 1 ELSE 0 END) never_booked
FROM fl LEFT JOIN fb ON fb.ph=fl.ph LEFT JOIN utm u ON u.ph10=RIGHT(fl.ph,10)
WHERE fl.fd BETWEEN '{lo}' AND '{end}' GROUP BY 1,2;""".format(lo=LO, end=END.isoformat())

LEAD_SRCS = ["GMB", "Google Ads", "Meta", "WhatsApp", "Walk-in", "Website", "Practo", "JustDial", "Newspaper", "YouTube", "Organic (untagged)", "Other"]
LFIELDS = ["new_leads", "booked_same", "booked_later", "never_booked"]

ONLINE_IDS = "'c7d8c9d2-f389-4e8f-a260-71110195b83f','ffe8d849-3099-48fe-a2df-e324c4befe56'"   # telehealth locations
# online SC booked by SERVICE day (national pool — dedup per patient/day)
ONL_BOOK_SQL = """WITH sc AS (
  SELECT a.patient_id, DATE(a.start_time + INTERVAL '5 hours 30 minutes') dt,
    ROW_NUMBER() OVER (PARTITION BY a.patient_id, DATE(a.start_time + INTERVAL '5 hours 30 minutes') ORDER BY a.id) rn
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
  WHERE a.deleted_at IS NULL AND a.location_id IN ({ids}) AND DATE(a.start_time + INTERVAL '5 hours 30 minutes') BETWEEN '{lo}' AND '{end}')
SELECT TO_CHAR(dt,'YYYY-MM-DD') d, COUNT(*) booked FROM sc WHERE rn=1 GROUP BY 1;""".format(ids=ONLINE_IDS, lo=LO, end=END.isoformat())
# online SC done/purchased/rev by COMPLETION day
ONL_DONE_SQL = """WITH inv AS (SELECT e.appointment_id ap_id, SUM(i.amount) amt FROM allo_encounters.encounters e
    JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.deleted_at IS NULL AND i.status='paid' WHERE e.deleted_at IS NULL GROUP BY 1),
  comp AS (SELECT a.id, DATE(COALESCE(a.actual_start_time,a.start_time,a.created_at) + INTERVAL '5 hours 30 minutes') d,
      ROW_NUMBER() OVER (PARTITION BY a.patient_id, DATE(COALESCE(a.actual_start_time,a.start_time,a.created_at) + INTERVAL '5 hours 30 minutes') ORDER BY a.id) rn
    FROM allo_consultations.appointments a
    JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
    WHERE a.deleted_at IS NULL AND a.status='COMPLETED' AND a.location_id IN ({ids})
      AND DATE(COALESCE(a.actual_start_time,a.start_time,a.created_at) + INTERVAL '5 hours 30 minutes') BETWEEN '{lo}' AND '{end}')
SELECT c.d, COUNT(*) done, SUM(CASE WHEN inv.ap_id IS NOT NULL THEN 1 ELSE 0 END) purchased,
  SUM(CASE WHEN inv.ap_id IS NOT NULL THEN COALESCE(inv.amt,0) ELSE 0 END) rev_paise
FROM comp c LEFT JOIN inv ON inv.ap_id=c.id WHERE c.rn=1 GROUP BY 1;""".format(ids=ONLINE_IDS, lo=LO, end=END.isoformat())

def slugify(loc, city):
    s = lambda x: "".join(ch if ch.isalnum() else "_" for ch in (x or "").strip().lower())
    return s(loc) + "_" + s(city)
CITY_ALIAS = {"bengaluru": "bangalore", "gurgaon": "gurugram"}
def norm_city(c): c = (c or "").strip().lower(); return CITY_ALIAS.get(c, c)

if __name__ == "__main__":
    src = json.load(open(os.path.join(ROOT, "data_source_recon.json")))
    sm = src["_meta"]
    clin = {}

    def C(slug):
        return clin.setdefault(slug, {"bottom": {"booked": Z(), "done": Z(), "purchased": Z(), "rev": Z(),
                "by_cat": {c: {"done": Z(), "purchased": Z(), "rev": Z()} for c in CATS}},
            "booked_by_source": {}, "done_by_source": {}, "by_doctor": {}})

    def doc(c, dr):
        return c["by_doctor"].setdefault(dr, {"booked": Z(), "done": Z(), "purchased": Z(), "rev": Z()})

    print("booked (service-day)…")
    for line in run_sql(BOOK_SQL):
        r = line.split("\t") if isinstance(line, str) else line
        if len(r) < 6: continue
        ct, lc, d, dr, s, bk = r[:6]
        if d not in idx: continue
        if s not in SOURCES: s = "untagged"
        i = idx[d]; c = C(slugify(lc, norm_city(ct)))
        try: bk = int(float(bk))
        except ValueError: continue
        c["bottom"]["booked"][i] += bk
        c["booked_by_source"].setdefault(s, Z())[i] += bk
        if dr: doc(c, dr)["booked"][i] += bk

    print("done / purchased / rev (completion-day)…")
    for line in run_sql(DONE_SQL):
        r = line.split("\t") if isinstance(line, str) else line
        if len(r) < 9: continue
        ct, lc, d, dr, cat, s, dn, pu, rvp = r[:9]
        if d not in idx: continue
        if cat not in CATS: cat = "Other"
        if s not in SOURCES: s = "untagged"
        i = idx[d]; c = C(slugify(lc, norm_city(ct)))
        try: dn = int(float(dn)); pu = int(float(pu)); rv = round(int(float(rvp)) / 100.0)
        except (ValueError, TypeError): continue
        for f, v in (("done", dn), ("purchased", pu), ("rev", rv)):
            c["bottom"][f][i] += v; c["bottom"]["by_cat"][cat][f][i] += v
            if dr: doc(c, dr)[f][i] += v
        c["done_by_source"].setdefault(s, Z())[i] += dn

    for c in clin.values():
        c["bottom"]["by_cat"] = {k: v for k, v in c["bottom"]["by_cat"].items() if any(any(v[f]) for f in ("done", "purchased", "rev"))}
        c["booked_by_source"] = {k: v for k, v in c["booked_by_source"].items() if any(v)}
        c["done_by_source"] = {k: v for k, v in c["done_by_source"].items() if any(v)}
        c["by_doctor"] = {k: {f: v[f] for f in v if any(v[f])} for k, v in c["by_doctor"].items() if any(any(v[f]) for f in v)}

    print("leads (daily by source)…")
    by_src = {s: {f: Z() for f in LFIELDS} for s in LEAD_SRCS}
    for line in run_sql(LEADS_SQL):
        r = line.split("\t") if isinstance(line, str) else line
        if len(r) < 6: continue
        d, s, nl, bs, bl, nb = r[:6]
        if d not in idx: continue
        if s not in LEAD_SRCS: s = "Other"
        i = idx[d]
        try:
            by_src[s]["new_leads"][i] += int(float(nl)); by_src[s]["booked_same"][i] += int(float(bs))
            by_src[s]["booked_later"][i] += int(float(bl)); by_src[s]["never_booked"][i] += int(float(nb))
        except (ValueError, TypeError): continue
    total = {f: [sum(by_src[s][f][i] for s in LEAD_SRCS) for i in range(NDAYS)] for f in LFIELDS}

    print("online (telehealth) booked / done…")
    onl = {"booked": Z(), "done": Z(), "purchased": Z(), "rev": Z()}
    for line in run_sql(ONL_BOOK_SQL):
        r = line.split("\t") if isinstance(line, str) else line
        if len(r) < 2: continue
        d, bk = r[:2]
        if d not in idx: continue
        try: onl["booked"][idx[d]] += int(float(bk))
        except ValueError: continue
    for line in run_sql(ONL_DONE_SQL):
        r = line.split("\t") if isinstance(line, str) else line
        if len(r) < 4: continue
        d, dn, pu, rvp = r[:4]
        if d not in idx: continue
        try: onl["done"][idx[d]] += int(float(dn)); onl["purchased"][idx[d]] += int(float(pu)); onl["rev"][idx[d]] += round(int(float(rvp)) / 100.0)
        except (ValueError, TypeError): continue

    out = {"_meta": {
        "online_bottom": {"total": onl, "by_cat": {}, "rev_cp": {}},
        "online_src": {},
        "weeks": DAYS, "daily": True,
        "display": sm.get("display", {}), "city_tier": sm.get("city_tier", {}),
        "clinic_age": sm.get("clinic_age", {}), "clinics": sm.get("clinics", []),
        "sources": SOURCES,
        "master_leads": {"sources": LEAD_SRCS, "by_source": by_src, "total": total, "note": "daily new leads by source (national)"},
        "note": "Daily master sheet — last %d days, service-day booked / completion-day done." % NDAYS},
        "clinics": clin}
    json.dump(out, open(os.path.join(ROOT, "data_daily_master.json"), "w"), separators=(",", ":"))
    nb = sum(sum(c["bottom"]["booked"]) for c in clin.values())
    nd = sum(sum(c["bottom"]["done"]) for c in clin.values())
    print("data_daily_master.json · %d clinics · %d days (%s → %s)" % (len(clin), NDAYS, DAYS[-1], DAYS[0]))
    print("network booked %d · done %d · leads %d" % (nb, nd, sum(total["new_leads"])))
    am = clin.get("ameerpet_hyderabad", {}).get("bottom", {})
    if am: print("Ameerpet booked[:7]:", am["booked"][:7], "done[:7]:", am["done"][:7])
