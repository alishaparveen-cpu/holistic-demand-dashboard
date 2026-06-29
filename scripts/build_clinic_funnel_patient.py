#!/usr/bin/env python3
"""PATIENT-LEVEL clinic funnel (leads + booking attribution). Per clinic/week:
LEAD side: unique RELEVANT lead-patients, one source per (patient,week) by priority
  (gmb_call>gpaid_call>gmb_web>practo>organic); of those booked a Screening Call SAME-week
  vs LATER (carryover) vs not, + pre-existing.
BOOKING side (reconcile total bookings): each week's screening-call bookings split into
  from THIS-week lead / from PRIOR-week lead (carry-in) / ATTRIBUTION GAP, where the gap is
  itself split: 'contacted-but-AI-not-relevant' (we had a call but the audit didn't mark it
  a relevant lead — possible AI miss) vs 'untracked' (no tracked contact at all — WhatsApp/
  direct/walk-in/phone-mismatch).
Resilient: per-query retry + resume (skips clinics already carrying lead_book.patient) +
saves after every clinic. Run: AWS_PROFILE=redshift-data python3 scripts/build_clinic_funnel_patient.py
"""
import os, sys, json, re, time
sys.path.insert(0, os.path.dirname(__file__))
import build_source_recon as SR
B=SR.B; WEEKS=SR.WEEKS; idx=SR.idx; NW=SR.NW; LO=SR.LO; run_sql=SR.run_sql; REL=SR.REL
ROOT=SR.ROOT; OUT=os.path.join(ROOT,"data_source_recon.json")
CFG=json.load(open(os.path.join(ROOT,"data_all_clinics_cfg.json")))
def Z(): return [0]*NW
DATE=re.compile(r'^202\d-\d\d-\d\d$')
KNOWN=set()
for c in CFG.values():
    for g in (c.get("gmb") or []): KNOWN.add(g[-10:])
    if c.get("paid"): KNOWN.add(c["paid"][-10:])
KNOWN_LIST="','".join(sorted(KNOWN))
WK=lambda col:"TO_CHAR(DATE_TRUNC('week', %s + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD')"%col

def q(sql):
    for t in range(4):
        try: return [l.split('\t') for l in run_sql(sql) if l.strip()]
        except Exception as e:
            if t==3: raise
            time.sleep(5)

def lead_rows(cfg):
    """(ph, wk, src) relevant lead contacts; also returns set of ALL contact phones (any relevance)."""
    rows=[]; allph=set(); loc=cfg["loc"].replace("'","''"); gnums="','".join(cfg.get("gmb") or [])
    def calls(numcond, src, ploc=""):
        # relevant rows
        for c in q("SELECT DISTINCT RIGHT(ec.\"from\",10), %s FROM allo_vendors.exotel_calls ec "
          "JOIN allo_analytics.call_analyses ca ON ca.call_id=ec.call_id AND ca.deleted_at IS NULL "
          "WHERE ec.routed_to='lead_to_call' AND ec.direction='inbound' AND %s %s "
          "AND ca.analysis.user_intent.result::varchar IN (%s) AND ec.start_time>='%s' AND ec.start_time<'2026-06-29'"
          %(WK("ec.start_time"),numcond,ploc,REL,LO)):
            if len(c)==2 and c[0]: rows.append((c[0],c[1],src))
        # all-contact phones (any relevance) for the gap analysis
        for c in q("SELECT DISTINCT RIGHT(ec.\"from\",10) FROM allo_vendors.exotel_calls ec "
          "WHERE ec.routed_to='lead_to_call' AND ec.direction='inbound' AND %s AND ec.start_time>='%s' AND ec.start_time<'2026-06-29'"
          %(numcond,LO)):
            if c[0]: allph.add(c[0])
    if cfg.get("gmb"): calls("RIGHT(ec.exotel_number,10) IN ('%s')"%gnums,"gmb_call")
    if cfg.get("paid"):
        ploc="" if cfg.get("paid_solo") else ("AND ca.analysis.user_intent.locality_mentioned.is_our_locality=true "
              "AND ca.analysis.user_intent.locality_mentioned.best_match::varchar='%s' "%loc)
        calls("RIGHT(ec.exotel_number,10)='%s'"%cfg["paid"],"gpaid_call",ploc)
    # organic (relevant + locality) + all-organic contacts
    calls("RIGHT(ec.exotel_number,10) NOT IN ('%s')"%KNOWN_LIST,"organic",
          "AND ca.analysis.user_intent.locality_mentioned.is_our_locality=true AND ca.analysis.user_intent.locality_mentioned.best_match::varchar='%s' "%loc)
    # gmb_web
    locslug=re.sub(r'\s+','-',cfg["loc"].strip().lower()); cityslug=re.sub(r'\s+','-',cfg["city"].strip().lower())
    cands=[locslug+'-clinic-gmb']+([cityslug+'-clinic-gmb'] if cfg.get("paid_solo") else [])
    inlist="','".join(x.replace("'","''") for x in cands)
    for c in q("SELECT DISTINCT RIGHT(phone_no,10), %s FROM allo_persons.lead WHERE LOWER(utm_source)='gmb' "
      "AND LOWER(utm_medium)='listing' AND LOWER(utm_campaign) IN ('%s') AND created_at>='%s' AND created_at<'2026-06-29'"
      %(WK("created_at"),inlist,LO)):
        if len(c)==2 and c[0] and len(c[0])>=10: rows.append((c[0],c[1],"gmb_web")); allph.add(c[0])
    return rows, allph

def bookings(cfg):
    """distinct (ph, booking_week) screening-call bookings at this clinic."""
    out=[]
    for c in q("SELECT RIGHT(p.phone_no,10), %s FROM allo_consultations.appointments a "
      "JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call' "
      "JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.city='%s' AND loc.locality='%s' AND loc.deleted_at IS NULL "
      "JOIN allo_persons.patient p ON p.id=a.patient_id WHERE a.deleted_at IS NULL "
      "AND a.created_at>='%s' AND a.created_at<'2026-06-29' GROUP BY 1,2"
      %(WK("a.created_at"),cfg["city"].replace("'","''"),cfg["loc"].replace("'","''"),LO)):
        if len(c)==2 and DATE.match(c[1] or ''): out.append((c[0],c[1]))
    return out

PRIO=["gmb_call","gpaid_call","gmb_web","practo","organic"]
def patient_funnel(cfg, practo_rows):
    rows, allph = lead_rows(cfg)
    rows = rows + practo_rows
    for ph,wk,src in practo_rows: allph.add(ph)
    bks = bookings(cfg)
    # lead-side: dedup one source per (ph,wk); relevant-lead weeks per phone
    best={}; lead_wks={}
    for ph,wk,src in rows:
        if wk not in idx: continue
        lead_wks.setdefault(ph,set()).add(wk)
        k=(ph,wk); p=PRIO.index(src) if src in PRIO else 99
        if k not in best or p<best[k][0]: best[k]=(p,src)
    # ALL screening-call booking weeks per phone — a (repeat or new) patient counts as booked if
    # they book a NEW screening call in the lead week (same) or a later week (carryover). A prior SC
    # alone does NOT count (funnel is per-screening-call; only a new SC at/after the lead converts).
    bkwks={}
    for ph,bwk in bks: bkwks.setdefault(ph,set()).add(bwk)
    o={"leads":Z(),"by_src":{s:Z() for s in PRIO},"booked_same":Z(),"booked_later":Z(),"not_booked":Z(),
       # booking-side reconciliation:
       "bk_total":Z(),"bk_thisweek_lead":Z(),"bk_prior_lead":Z(),"bk_gap_aimiss":Z(),"bk_gap_untracked":Z()}
    for (ph,wk),(p,src) in best.items():
        i=idx[wk]; o["leads"][i]+=1; o["by_src"][src][i]+=1
        ws=bkwks.get(ph)
        if ws and wk in ws: o["booked_same"][i]+=1
        elif ws and any(b>wk for b in ws): o["booked_later"][i]+=1
        else: o["not_booked"][i]+=1
    for ph,bwk in bks:
        if bwk not in idx: continue
        i=idx[bwk]; o["bk_total"][i]+=1
        wks=lead_wks.get(ph)
        if wks and bwk in wks: o["bk_thisweek_lead"][i]+=1
        elif wks and min(wks)<bwk: o["bk_prior_lead"][i]+=1
        elif ph in allph: o["bk_gap_aimiss"][i]+=1     # contacted us but not counted a relevant lead
        else: o["bk_gap_untracked"][i]+=1               # no tracked contact (WhatsApp/direct/walk-in/mismatch)
    return o

def practo_rows_for(cfg, by_loc):
    locs=[cfg["loc"]]+SR.PRACTO_ALIAS.get(cfg["loc"],[]); out=[]
    for pl in locs:
        for (wk,ph) in by_loc.get(pl,set()):
            if wk in idx: out.append((ph,wk,"practo"))
    return out

if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument("--only"); ap.add_argument("--force",action="store_true"); a=ap.parse_args()
    d=json.load(open(OUT)); by_loc,_=SR.load_practo_sheet(); ok=skip=0
    for slug,c in d["clinics"].items():
        cfg=CFG.get(slug)
        if not cfg: continue
        if a.only and a.only.lower() not in slug.lower(): continue
        if not a.force and not a.only and (c.get("lead_book",{}) or {}).get("patient"): skip+=1; continue
        try:
            pf=patient_funnel(cfg, practo_rows_for(cfg,by_loc))
            c.setdefault("lead_book",{})["patient"]=pf; ok+=1
            print("[ok %d] %-26s leads=%s bkSame=%s carry=%s | bkTot=%s thisLd=%s priorLd=%s aimiss=%s untrk=%s"%(
              ok,cfg.get("disp",slug),sum(pf["leads"]),sum(pf["booked_same"]),sum(pf["booked_later"]),
              sum(pf["bk_total"]),sum(pf["bk_thisweek_lead"]),sum(pf["bk_prior_lead"]),sum(pf["bk_gap_aimiss"]),sum(pf["bk_gap_untracked"])),flush=True)
            if not a.only: json.dump(d,open(OUT,"w"),separators=(",",":"))   # save after each clinic (resume-safe)
        except Exception as e:
            print("  [warn] %s: %s"%(cfg.get("disp",slug),str(e)[:120]))
    print("done. built %d, skipped(already had) %d"%(ok,skip))
