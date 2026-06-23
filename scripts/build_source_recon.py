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
import os, sys, json
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
      WHERE a.deleted_at IS NULL AND a.created_at >= '{lo}' AND a.created_at < '2026-06-22'),
     bk AS (SELECT patient_id, ph, bts, wk FROM bk0 WHERE rn=1),
     fsc AS (SELECT a.patient_id, MIN(a.created_at) f FROM allo_consultations.appointments a
       JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call' WHERE a.deleted_at IS NULL GROUP BY 1),
     gc AS (SELECT DISTINCT RIGHT("from",10) ph FROM allo_vendors.exotel_calls WHERE RIGHT(exotel_number,10) IN ('{gmb}') AND routed_to='lead_to_call' AND direction='inbound' AND start_time>='2026-02-15'),
     pc AS (SELECT DISTINCT RIGHT("from",10) ph FROM allo_vendors.exotel_calls WHERE RIGHT(exotel_number,10)='{paid}' AND routed_to='lead_to_call' AND direction='inbound' AND start_time>='2026-02-15'),
     u AS (SELECT ph,us,um,g,f FROM (
        SELECT RIGHT(phone_no,10) ph, LOWER(COALESCE(utm_source,'')) us, LOWER(COALESCE(utm_medium,'')) um,
          CASE WHEN gclid<>'' THEN 1 ELSE 0 END g, CASE WHEN fbclid<>'' THEN 1 ELSE 0 END f,
          ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY created_at DESC) rn
        FROM allo_persons.lead WHERE created_at>='2026-01-15' AND (utm_source IS NOT NULL OR gclid<>'' OR fbclid<>'')) z WHERE rn=1)
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
        AND (ec.start_time+INTERVAL '5 hours 30 minutes') >= '{lo}' AND (ec.start_time+INTERVAL '5 hours 30 minutes') < '2026-06-22'
      GROUP BY 1,3),
     bk AS (SELECT DISTINCT RIGHT(p.phone_no,10) ph FROM allo_consultations.appointments a
       JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.city='{city}' AND loc.locality='{loc}' AND loc.deleted_at IS NULL
       JOIN allo_persons.patient p ON p.id=a.patient_id
       JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
       WHERE a.deleted_at IS NULL AND a.created_at>='2026-02-15')
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

def main():
    out = {"_meta": {"weeks": WEEKS, "sources": SOURCES,
            "clinics": [k for k in CLINICS], "display": {k: CLINICS[k]["disp"] for k in CLINICS},
            "note": "Bookings deduped per patient/week, source priority-assigned (call match > UTM). Lead->book only for call channels + GMB web (clinic-attributable); other channels are booked-only. Untagged = no Exotel call + no UTM."},
        "clinics": {}}
    for slug, cfg in CLINICS.items():
        by_src, un_new, un_rep = bookings_by_source(cfg)
        gmb_lb = call_lead_book(cfg["gmb"], None, cfg, 'gmb')
        paid_lb = call_lead_book(None, cfg["paid"], cfg, 'paid') if cfg["paid"] else {"leads":Z(),"booked":Z(),"notbooked":Z()}
        # GMB web from the MH funnel data (already computed there)
        mh = json.load(open(os.path.join(ROOT, "data_mh_%s.json" % slug)))
        web = mh.get("leads", {}).get("gmb_web", {"total":Z(),"booked":Z(),"notbooked":Z()})
        out["clinics"][slug] = {"by_source": by_src, "untagged_new": un_new, "untagged_repeat": un_rep,
            "lead_book": {"gmb_call": gmb_lb, "gmb_web": {"leads": web["total"], "booked": web["booked"], "notbooked": web["notbooked"]},
                          "gpaid_call": paid_lb}}
        tot = sum(sum(by_src[s]) for s in SOURCES)
        print(f"[{slug}] {cfg['disp']}: {tot} bookings/12wk | untagged {sum(by_src['untagged'])} (new {sum(un_new)}/rep {sum(un_rep)}) | gmb_call L->B {sum(gmb_lb['booked'])}/{sum(gmb_lb['leads'])}")
    json.dump(out, open(os.path.join(ROOT, "data_source_recon.json"), "w"), separators=(",",":"))
    print("wrote data_source_recon.json")

if __name__ == "__main__":
    main()
