#!/usr/bin/env python3
"""Standalone Source-Reconciliation data for the MH clinics → data_source_recon.json.
Does NOT touch the MH funnel. Per clinic, weekly:
  A) bookings by SOURCE (deduped per patient/week, priority-assigned) — GMB call/web/WhatsApp,
     Google paid call/web, Practo, Meta, Organic, UNTAGGED. Sums to total bookings.
  B) UNTAGGED bookings split NEW vs REPEAT (first-ever Screening Call vs prior).
  C) Lead -> Booked / Didn't / book% for the cleanly clinic-attributable channels:
     GMB call (Exotel), GMB web (campaign), Google paid call (Exotel). GMB-web reuses the
     same logic as the MH funnel. Other channels appear in (A) only (no clean clinic lead universe).
Run: AWS_PROFILE=redshift-data python3 scripts/build_source_recon.py
"""
import os, sys, json, csv, io, datetime, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
import build_mh_funnels as B   # reuse WEEKS, idx, NW, LO, run_sql, CLINICS, GMBWEB_CAMP

ROOT = B.ROOT; WEEKS = B.WEEKS; idx = B.idx; NW = B.NW; LO = B.LO; run_sql = B.run_sql
CLINICS = B.CLINICS; GMBWEB_CAMP = B.GMBWEB_CAMP
SOURCES = ["gmb_call","gmb_web","gmb_wa","gpaid_call","gpaid_web","practo","meta","organic","untagged"]

def Z(): return [0]*NW

# ---- A + B: bookings by source (deduped) + untagged new/repeat ----
def bookings_by_source(cfg):
    gmb_in = "','".join(cfg["gmb"]); paid = cfg["paid"] or "0000000000"
    sql = """WITH bk0 AS (
      SELECT a.patient_id, RIGHT(p.phone_no,10) ph, a.created_at bts,
        TO_CHAR(DATE_TRUNC('week', a.created_at+INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk,
        ROW_NUMBER() OVER (PARTITION BY a.patient_id, TO_CHAR(DATE_TRUNC('week',a.created_at+INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') ORDER BY a.created_at) rn
      FROM allo_consultations.appointments a
      JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.city='{city}' AND loc.locality='{loc}' AND loc.deleted_at IS NULL
      JOIN allo_persons.patient p ON p.id=a.patient_id
      JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
      WHERE a.deleted_at IS NULL AND a.created_at >= '{lo}' AND a.created_at < '2026-06-29'),
     bk AS (SELECT patient_id, ph, bts, wk FROM bk0 WHERE rn=1),
     fsc AS (SELECT a.patient_id, MIN(a.created_at) f FROM allo_consultations.appointments a
       JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call' WHERE a.deleted_at IS NULL GROUP BY 1),
     gc AS (SELECT DISTINCT RIGHT("from",10) ph FROM allo_vendors.exotel_calls WHERE RIGHT(exotel_number,10) IN ('{gmb}') AND routed_to='lead_to_call' AND direction='inbound' AND start_time>='2025-06-23'),
     pc AS (SELECT DISTINCT RIGHT("from",10) ph FROM allo_vendors.exotel_calls WHERE RIGHT(exotel_number,10)='{paid}' AND routed_to='lead_to_call' AND direction='inbound' AND start_time>='2025-06-23'),
     u AS (SELECT ph,us,um,g,f FROM (
        SELECT RIGHT(phone_no,10) ph, LOWER(COALESCE(utm_source,'')) us, LOWER(COALESCE(utm_medium,'')) um,
          CASE WHEN gclid<>'' THEN 1 ELSE 0 END g, CASE WHEN fbclid<>'' THEN 1 ELSE 0 END f,
          ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY created_at DESC) rn
        FROM allo_persons.lead WHERE created_at>='2025-06-23' AND (utm_source IS NOT NULL OR gclid<>'' OR fbclid<>'')) z WHERE rn=1)
    SELECT bk.wk,
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
      CASE WHEN bk.bts<=fsc.f THEN 'new' ELSE 'repeat' END isnew,
      COUNT(*) n
    FROM bk LEFT JOIN gc ON gc.ph=bk.ph LEFT JOIN pc ON pc.ph=bk.ph LEFT JOIN u ON u.ph=bk.ph LEFT JOIN fsc ON fsc.patient_id=bk.patient_id
    GROUP BY 1,2,3;""".format(city=cfg["city"].replace("'","''"), loc=cfg["loc"].replace("'","''"),
        lo=LO, gmb=gmb_in, paid=paid)
    by_src = {s: Z() for s in SOURCES}
    untag_new = Z(); untag_rep = Z()
    for line in run_sql(sql):
        c = line.split("\t")
        if len(c) < 4 or c[0] not in idx: continue
        wk, src, isnew, n_s = c
        if wk not in idx or src not in by_src: continue
        i = idx[wk]
        try: n = int(float(n_s))
        except ValueError: continue
        by_src[src][i] += n
        if src == 'untagged':
            (untag_new if isnew == 'new' else untag_rep)[i] += n
    return by_src, untag_new, untag_rep

# ---- C: lead -> booked for the call channels (web reuses MH funnel data) ----
def call_lead_book(num_list, paid_num, cfg, kind):
    # kind 'gmb' → callers to GMB number; 'paid' → callers to paid number with clinic-intent
    if kind == 'gmb':
        where = "RIGHT(ec.exotel_number,10) IN ('%s')" % "','".join(num_list)
        loc_filter = ""
    else:
        where = "RIGHT(ec.exotel_number,10)='%s'" % paid_num
        loc_filter = ("AND ca.analysis.user_intent.locality_mentioned.is_our_locality=true "
                      "AND ca.analysis.user_intent.locality_mentioned.best_match::varchar='%s'" % cfg["loc"].replace("'","''"))
        if cfg.get("paid_solo"): loc_filter = ""   # single-clinic city: all city paid calls
    src_tbl = ("allo_vendors.exotel_calls ec" if kind=='gmb'
               else "allo_analytics.call_analyses ca JOIN allo_vendors.exotel_calls ec ON ec.call_id=ca.call_id AND ec.routed_to='lead_to_call'")
    extra = "ec.routed_to='lead_to_call' AND ec.direction='inbound'" if kind=='gmb' else "ca.deleted_at IS NULL"
    sql = """WITH calls AS (
      SELECT RIGHT(ec."from",10) ph, MIN(ec.start_time) ct,
        TO_CHAR(DATE_TRUNC('week', ec.start_time+INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk
      FROM {src}
      WHERE {where} AND {extra} {locf}
        AND (ec.start_time+INTERVAL '5 hours 30 minutes') >= '{lo}' AND (ec.start_time+INTERVAL '5 hours 30 minutes') < '2026-06-29'
      GROUP BY 1,3),
     bk AS (SELECT DISTINCT RIGHT(p.phone_no,10) ph FROM allo_consultations.appointments a
       JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.city='{city}' AND loc.locality='{loc}' AND loc.deleted_at IS NULL
       JOIN allo_persons.patient p ON p.id=a.patient_id
       JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
       WHERE a.deleted_at IS NULL AND a.created_at>='2025-06-23')
    SELECT calls.wk, COUNT(DISTINCT calls.ph) leads,
      COUNT(DISTINCT CASE WHEN bk.ph IS NOT NULL THEN calls.ph END) booked
    FROM calls LEFT JOIN bk ON bk.ph=calls.ph GROUP BY 1;""".format(
        src=src_tbl, where=where, extra=extra, locf=loc_filter, lo=LO,
        city=cfg["city"].replace("'","''"), loc=cfg["loc"].replace("'","''"))
    leads = Z(); booked = Z()
    for line in run_sql(sql):
        c = line.split("\t")
        if len(c) < 3 or c[0] not in idx: continue
        i = idx[c[0]]
        try: leads[i]=int(float(c[1])); booked[i]=int(float(c[2]))
        except ValueError: pass
    return {"leads": leads, "booked": booked, "notbooked": [leads[i]-booked[i] for i in range(NW)]}

REL = "'TALK_TO_DOCTOR','TALK_TO_THERAPIST','NEEDS_TESTS','NEEDS_MEDS','BOOK_APPOINTMENT','BOOK_TEST','BOOK_SLOT'"
# ---- call funnel: calls -> answered/missed -> relevant callers -> booked/didn't ----
def call_funnel(cfg, kind):
    if kind == 'gmb':
        where = "RIGHT(ec.exotel_number,10) IN ('%s')" % "','".join(cfg["gmb"]); andloc = ""; locsel = "0 locok"
    else:
        where = "RIGHT(ec.exotel_number,10)='%s'" % (cfg["paid"] or "0")
        if cfg.get("paid_solo"):
            andloc = ""; locsel = "0 locok"
        else:
            andloc = "AND aud.locok=1"
            locsel = ("MAX(CASE WHEN ca.analysis.user_intent.locality_mentioned.is_our_locality=true "
                      "AND ca.analysis.user_intent.locality_mentioned.best_match::varchar='%s' THEN 1 ELSE 0 END) locok" % cfg["loc"].replace("'","''"))
    sql = """WITH calls AS (
      SELECT ec.call_id, RIGHT(ec."from",10) ph, ec.status,
        TO_CHAR(DATE_TRUNC('week', ec.start_time+INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk
      FROM allo_vendors.exotel_calls ec
      WHERE {where} AND ec.routed_to='lead_to_call' AND ec.direction='inbound'
        AND (ec.start_time+INTERVAL '5 hours 30 minutes')>='{lo}' AND (ec.start_time+INTERVAL '5 hours 30 minutes')<'2026-06-29'),
     aud AS (SELECT ca.call_id,
        MAX(CASE WHEN ca.analysis.user_intent.result::varchar IN ({rel}) THEN 1 ELSE 0 END) rel, {locsel}
       FROM allo_analytics.call_analyses ca WHERE ca.deleted_at IS NULL GROUP BY 1),
     bk AS (SELECT DISTINCT RIGHT(p.phone_no,10) ph FROM allo_consultations.appointments a
       JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.city='{city}' AND loc.locality='{loc}' AND loc.deleted_at IS NULL
       JOIN allo_persons.patient p ON p.id=a.patient_id
       JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
       WHERE a.deleted_at IS NULL AND a.created_at>='2025-06-23')
    SELECT calls.wk,
      COUNT(*) total,
      SUM(CASE WHEN calls.status='completed' THEN 1 ELSE 0 END) answered,
      SUM(CASE WHEN calls.status<>'completed' THEN 1 ELSE 0 END) missed,
      COUNT(DISTINCT CASE WHEN aud.rel=1 {andloc} THEN calls.ph END) rel_callers,
      COUNT(DISTINCT CASE WHEN aud.rel=1 {andloc} AND bk.ph IS NOT NULL THEN calls.ph END) booked
    FROM calls LEFT JOIN aud ON aud.call_id=calls.call_id LEFT JOIN bk ON bk.ph=calls.ph
    GROUP BY 1;""".format(where=where, rel=REL, locsel=locsel, andloc=andloc, lo=LO,
        city=cfg["city"].replace("'","''"), loc=cfg["loc"].replace("'","''"))
    d = {k: Z() for k in ("total","answered","missed","relevant","booked")}
    for line in run_sql(sql):
        c = line.split("\t")
        if len(c) < 6 or c[0] not in idx: continue
        i = idx[c[0]]
        try:
            d["total"][i]=int(float(c[1])); d["answered"][i]=int(float(c[2])); d["missed"][i]=int(float(c[3]))
            d["relevant"][i]=int(float(c[4])); d["booked"][i]=int(float(c[5]))
        except ValueError: pass
    d["notbooked"] = [d["relevant"][i]-d["booked"][i] for i in range(NW)]
    return d

# ---- Google paid WEB lead->book (single-clinic cities only; multi-clinic city-level not isolatable) ----
SINGLE_CLINIC_CITIES = ("Hubli",)   # single-clinic cities w/o a separate paid call number → web still isolatable
def gpaid_web_leadbook(cfg, bkphones):
    if not (cfg.get("paid_solo") or cfg["city"] in SINGLE_CLINIC_CITIES):   # multi-clinic city — paid web is city-level
        return None
    tok = {"Coimbatore":"coimbatore","Jaipur":"jaipur","Hubli":"hubballi"}.get(cfg["city"], cfg["city"].lower())
    sql = """SELECT TO_CHAR(DATE_TRUNC('week', created_at+INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk,
      RIGHT(phone_no,10) ph
    FROM allo_persons.lead
    WHERE (gclid<>'' OR LOWER(utm_source)='google')
      AND (LOWER(utm_campaign) LIKE 't1_{tok}%' OR LOWER(utm_campaign) LIKE 't2_{tok}%')
      AND created_at>='{lo}' AND created_at<'2026-06-29';""".format(tok=tok, lo=LO)
    leads = Z(); booked = Z(); seen = set()
    for line in run_sql(sql):
        c = line.split("\t")
        if len(c) < 2 or c[0] not in idx: continue
        wk, ph = c[0], c[1].strip()
        if len(ph) < 10 or (wk, ph) in seen: continue
        seen.add((wk, ph)); i = idx[wk]; leads[i]+=1
        if ph in bkphones: booked[i]+=1
    return {"leads": leads, "booked": booked, "notbooked": [leads[i]-booked[i] for i in range(NW)]}

# ---- Practo lead -> book (connections sheet has Practice Locality + patient phone) ----
PRACTO_SID = "1pTPQgdSUaomRuj_49dARVJ4Vtiy34uE73X4gqqkwlaE"
def load_practo_sheet():
    url = "https://docs.google.com/spreadsheets/d/%s/export?format=csv&sheet=Practo" % PRACTO_SID
    data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"}), timeout=180).read().decode("utf-8","replace")
    rows = list(csv.reader(io.StringIO(data))); hdr = [h.strip() for h in rows[0]]
    li = hdr.index("Practice Locality"); ph = hdr.index("Patient_Phone_Number"); dt = hdr.index("Date")
    dc = hdr.index("Doctor Name") if "Doctor Name" in hdr else -1
    by_loc = {}; by_loc_doc = {}
    for r in rows[1:]:
        if len(r) <= max(li, ph, dt): continue
        loc = r[li].strip()
        try: d = datetime.datetime.strptime(r[dt].strip(), "%d-%m-%Y").date()
        except ValueError: continue
        mon = (d - datetime.timedelta(days=d.weekday())).isoformat()
        if mon not in idx: continue
        p = "".join(ch for ch in r[ph] if ch.isdigit())[-10:]
        if len(p) < 10: continue
        by_loc.setdefault(loc, set()).add((mon, p))   # dedupe distinct (week, phone)
        if dc >= 0 and len(r) > dc:
            doc = r[dc].strip() or "Unknown"
            by_loc_doc.setdefault(loc, {}).setdefault(doc, set()).add((mon, p))
    return by_loc, by_loc_doc

def get_booking_phones(cfg):
    sql = """SELECT DISTINCT RIGHT(p.phone_no,10) ph FROM allo_consultations.appointments a
      JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.city='{city}' AND loc.locality='{loc}' AND loc.deleted_at IS NULL
      JOIN allo_persons.patient p ON p.id=a.patient_id
      JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
      WHERE a.deleted_at IS NULL AND a.created_at>='2025-06-23';""".format(city=cfg["city"].replace("'","''"), loc=cfg["loc"].replace("'","''"))
    return set(l.split("\t")[0] for l in run_sql(sql) if l.strip())

# Clinic locality -> extra Practo "Practice Locality" strings that are the SAME clinic
# (validated 2026-06-24 against allo_health.locations; single-clinic-city orphans route to the lone clinic).
PRACTO_ALIAS = {
    "Electronic City": ["Electronics City"], "Sahakara Nagar": ["Sahakaranagar"],
    "Borivali": ["Borivali East"], "Dadar": ["Dadar West"], "Chinchwad": ["Pimpri-Chinchwad"],
    "Thoraipakkam": ["Okkiyam Thuraipakkam"], "Gulmohar": ["Gulmohar Colony"],
    "Suryaraopeta": ["Suryaraopet"], "Vidya Nagar": ["Hubli Vidyanagar"],
    "Vaishali Nagar": ["Khatipura"], "Ashok Nagar": ["Bariatu"],
    "Tatya Tope Nagar": ["Mankapur Ring Road"], "Falnir Rd": ["Falnir"], "Thane": ["Thane West"],
}
def practo_leadbook(cfg, practo_by_loc, bkphones, practo_by_loc_doc=None):
    locs = [cfg["loc"]] + PRACTO_ALIAS.get(cfg["loc"], [])
    pairs = set()
    for pl in locs: pairs |= practo_by_loc.get(pl, set())
    leads = Z(); booked = Z()
    for (wk, ph) in pairs:
        i = idx[wk]; leads[i] += 1
        if ph in bkphones: booked[i] += 1
    out = {"leads": leads, "booked": booked, "notbooked": [leads[i]-booked[i] for i in range(NW)]}
    if practo_by_loc_doc:
        docagg = {}
        for pl in locs:
            for doc, prs in practo_by_loc_doc.get(pl, {}).items():
                docagg.setdefault(doc, set()).update(prs)
        docs = []
        for doc, prs in docagg.items():
            dl = Z(); db = Z()
            for (wk, ph) in prs:
                i = idx[wk]; dl[i] += 1
                if ph in bkphones: db[i] += 1
            docs.append({"name": doc, "leads": dl, "booked": db, "notbooked": [dl[i]-db[i] for i in range(NW)]})
        out["doctors"] = sorted(docs, key=lambda o: -sum(o["leads"]))
    return out

# ---- Availability: bookable roster slots + distinct hours + days, split weekday/weekend, by doctor ----
def availability(cfg):
    FROM = ("""FROM allo_consultations.roster_slots rs
      JOIN allo_health.locations loc ON loc.id=rs.location_id AND loc.deleted_at IS NULL
      WHERE rs.type_id='cd02525c-1528-4047-a12c-1ad526c28c9a' AND rs.available_for_booking=1
        AND rs.start_time >= '{lo}' AND rs.start_time < '2026-06-29'
        AND loc.city='{city}' AND COALESCE(loc.locality,loc.name,'')='{loc}'"""
      ).format(lo=LO, city=cfg["city"].replace("'","''"), loc=cfg["loc"].replace("'","''"))
    IST = "rs.start_time + INTERVAL '5 hours 30 minutes'"
    # clinic totals (slots / hours / days, with weekend split)
    sql = """WITH s AS (SELECT TO_CHAR(DATE_TRUNC('week', {ist}),'YYYY-MM-DD') wk,
        EXTRACT(DOW FROM {ist}) dow, DATE_TRUNC('hour', {ist}) hr, DATE({ist}) dt
      {f})
    SELECT wk, COUNT(*) st, SUM(CASE WHEN dow IN (0,6) THEN 1 ELSE 0 END) sw,
      COUNT(DISTINCT hr) ht, COUNT(DISTINCT CASE WHEN dow IN (0,6) THEN hr END) hw,
      COUNT(DISTINCT dt) dt_t, COUNT(DISTINCT CASE WHEN dow IN (0,6) THEN dt END) dt_w
    FROM s GROUP BY 1;""".format(ist=IST, f=FROM)
    d = {k: Z() for k in ("slots_total","slots_we","hrs_total","hrs_we","days_total","days_we")}
    for line in run_sql(sql):
        c = line.split("\t")
        if len(c) < 7 or c[0] not in idx: continue
        i = idx[c[0]]
        try:
            d["slots_total"][i]=int(float(c[1])); d["slots_we"][i]=int(float(c[2]))
            d["hrs_total"][i]=int(float(c[3])); d["hrs_we"][i]=int(float(c[4]))
            d["days_total"][i]=int(float(c[5])); d["days_we"][i]=int(float(c[6]))
        except ValueError: pass
    for m in ("slots","hrs","days"):
        d[m+"_wd"]=[d[m+"_total"][i]-d[m+"_we"][i] for i in range(NW)]
    # per-doctor (weekly slots / hours / days)
    sqlD = """WITH s AS (SELECT rs.provider_id pid, TO_CHAR(DATE_TRUNC('week', {ist}),'YYYY-MM-DD') wk,
        DATE_TRUNC('hour', {ist}) hr, DATE({ist}) dt {f})
    SELECT COALESCE(p.name,'Unknown') doctor, s.wk, COUNT(*) st, COUNT(DISTINCT hr) ht, COUNT(DISTINCT dt) dt_t
    FROM s LEFT JOIN allo_persons.providers p ON p.id=s.pid GROUP BY 1,2;""".format(ist=IST, f=FROM)
    docs = {}
    for line in run_sql(sqlD):
        c = line.split("\t")
        if len(c) < 5 or c[1] not in idx: continue
        nm = c[0].strip() or "Unknown"; i = idx[c[1]]
        o = docs.setdefault(nm, {"name":nm,"slots":Z(),"hrs":Z(),"days":Z()})
        try:
            o["slots"][i]=int(float(c[2])); o["hrs"][i]=int(float(c[3])); o["days"][i]=int(float(c[4]))
        except ValueError: pass
    d["doctors"] = sorted(docs.values(), key=lambda o: -sum(o["slots"]))
    return d

# ---- GMB/Google reviews per week, split positive (>=4*) / negative (<=3*) ----
def reviews(cfg):
    sql = """SELECT TO_CHAR(DATE_TRUNC('week', er.review_date + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk,
      COUNT(*) n, SUM(CASE WHEN er.rating>=4 THEN 1 ELSE 0 END) pos, SUM(CASE WHEN er.rating<=3 THEN 1 ELSE 0 END) neg
    FROM allo_health.external_reviews er
    JOIN allo_health.locations loc ON loc.id=er.reviewed_for_id AND loc.deleted_at IS NULL
    WHERE er.deleted_at IS NULL AND LOWER(er.platform) IN ('google','gmb')
      AND er.review_date >= '{lo}' AND er.review_date < '2026-06-29'
      AND loc.city='{city}' AND loc.locality='{loc}'
    GROUP BY 1;""".format(lo=LO, city=cfg["city"].replace("'","''"), loc=cfg["loc"].replace("'","''"))
    d = {"total": Z(), "pos": Z(), "neg": Z()}
    for line in run_sql(sql):
        c = line.split("\t")
        if len(c) < 4 or c[0] not in idx: continue
        i = idx[c[0]]
        try: d["total"][i]=int(float(c[1])); d["pos"][i]=int(float(c[2])); d["neg"][i]=int(float(c[3]))
        except ValueError: pass
    return d

def main():
    practo_by_loc, practo_by_loc_doc = load_practo_sheet()
    out = {"_meta": {"weeks": WEEKS, "sources": SOURCES,
            "clinics": [k for k in CLINICS], "display": {k: CLINICS[k]["disp"] for k in CLINICS},
            "note": "Bookings deduped per patient/week, source priority-assigned (call match > UTM). Lead->book only for call channels + GMB web (clinic-attributable); other channels are booked-only. Untagged = no Exotel call + no UTM."},
        "clinics": {}}
    for slug, cfg in CLINICS.items():
        by_src, un_new, un_rep = bookings_by_source(cfg)
        bkph = get_booking_phones(cfg)
        gmb_lb = call_funnel(cfg, 'gmb')
        paid_lb = call_funnel(cfg, 'paid') if cfg["paid"] else None
        gpw_lb = gpaid_web_leadbook(cfg, bkph)
        mh = json.load(open(os.path.join(ROOT, "data_mh_%s.json" % slug)))
        web = mh.get("leads", {}).get("gmb_web", {"total":Z(),"booked":Z(),"notbooked":Z()})
        bottom = mh.get("bottom", {}).get("total", {})   # booked/done/purchased/rev — reused from MH data
        out["clinics"][slug] = {"by_source": by_src, "untagged_new": un_new, "untagged_repeat": un_rep,
            "lead_book": {"gmb_call": gmb_lb, "gmb_web": {"leads": web["total"], "booked": web["booked"], "notbooked": web["notbooked"]},
                          "gpaid_call": paid_lb, "gpaid_web": gpw_lb,
                          "practo": practo_leadbook(cfg, practo_by_loc, bkph, practo_by_loc_doc)},
            "bottom": {"booked": bottom.get("booked", Z()), "done": bottom.get("done", Z()),
                       "purchased": bottom.get("purchased", Z()), "rev": bottom.get("rev", Z())},
            "reach": mh.get("reach", {}), "reviews": reviews(cfg)}
        tot = sum(sum(by_src[s]) for s in SOURCES)
        print(f"[{slug}] {cfg['disp']}: {tot} bk | untag {sum(by_src['untagged'])} (n{sum(un_new)}/r{sum(un_rep)}) | gmb-call {sum(gmb_lb['total'])}calls→{sum(gmb_lb['relevant'])}rel→{sum(gmb_lb['booked'])}bk")
    json.dump(out, open(os.path.join(ROOT, "data_source_recon.json"), "w"), separators=(",",":"))
    print("wrote data_source_recon.json")

if __name__ == "__main__":
    main()
