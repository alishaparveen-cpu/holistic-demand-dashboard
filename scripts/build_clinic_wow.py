#!/usr/bin/env python3
"""Build data_source_recon.json for ALL clinics (Clinic WoW page).
Reads data_all_clinics_cfg.json (clinic→gmb/paid/paid_solo/practo_alias, derived 2026-06-24)
and reuses build_source_recon's per-clinic functions. Computes everything inline (no data_mh
dependency): bottom via build_mh_funnels.get_bottom, gmb-web via a generic campaign match,
reviews + availability + Practo per clinic. reach (GMB/Google impressions) deferred → {}.
Run: AWS_PROFILE=redshift-data python3 scripts/build_clinic_wow.py
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(__file__))
import build_source_recon as SR
import build_mh_funnels as B

WEEKS=SR.WEEKS; idx=SR.idx; NW=SR.NW; Z=SR.Z; run_sql=SR.run_sql; LO=SR.LO
ROOT=SR.ROOT
CFG=json.load(open(os.path.join(ROOT,"data_all_clinics_cfg.json")))

def gmbweb_generic(cfg, bkph):
    locslug=re.sub(r'\s+','-',cfg["loc"].strip().lower())
    cityslug=re.sub(r'\s+','-',cfg["city"].strip().lower())
    cands=[locslug+'-clinic-gmb']
    if cfg.get('paid_solo'): cands.append(cityslug+'-clinic-gmb')
    inlist="','".join(c.replace("'","''") for c in cands)
    sql=("SELECT TO_CHAR(DATE_TRUNC('week', created_at+INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk, "
         "RIGHT(phone_no,10) ph FROM allo_persons.lead WHERE LOWER(utm_source)='gmb' AND LOWER(utm_medium)='listing' "
         "AND LOWER(utm_campaign) IN ('%s') AND created_at>='%s' AND created_at<'2026-06-22';"%(inlist,LO))
    leads=Z();booked=Z();seen=set()
    for line in run_sql(sql):
        c=line.split('\t')
        if len(c)<2 or c[0] not in idx: continue
        wk,ph=c[0],c[1].strip()
        if len(ph)<10 or (wk,ph) in seen: continue
        seen.add((wk,ph));i=idx[wk];leads[i]+=1
        if ph in bkph: booked[i]+=1
    return {"leads":leads,"booked":booked,"notbooked":[leads[i]-booked[i] for i in range(NW)]}

OUTPATH=os.path.join(ROOT,"data_source_recon.json")
def main():
    pbl,pbld=SR.load_practo_sheet()
    # resume: keep any already-built clinics (skip them) from a prior partial run
    out={"_meta":{"weeks":WEEKS,"sources":SR.SOURCES,"clinics":[],"display":{},
        "note":"All-clinic WoW. Bookings deduped per patient/week, source priority-assigned (call match > UTM). GMB/Google reach (impressions/CTR) deferred. Reviews provisional (external_reviews)."},
        "clinics":{}}
    if os.path.exists(OUTPATH):
        try:
            prev=json.load(open(OUTPATH))
            if prev.get("_meta",{}).get("note","").startswith("All-clinic"):
                out["clinics"]=prev["clinics"]; out["_meta"]["display"]=prev["_meta"].get("display",{})
                out["_meta"]["clinics"]=prev["_meta"].get("clinics",[])
                print("[resume] %d clinics already built"%len(out["clinics"]))
        except Exception: pass
    order=sorted(CFG.items(), key=lambda kv:-kv[1].get("bookings",0))
    ok=fail=0
    for slug,cfg in order:
        if slug in out["clinics"]:
            continue
        try:
            by_src,un_new,un_rep=SR.bookings_by_source(cfg)
            bkph=SR.get_booking_phones(cfg)
            gmb_lb=SR.call_funnel(cfg,'gmb') if cfg["gmb"] else None
            paid_lb=SR.call_funnel(cfg,'paid') if cfg["paid"] else None
            gpw=SR.gpaid_web_leadbook(cfg,bkph)
            web=gmbweb_generic(cfg,bkph)
            practo=SR.practo_leadbook(cfg,pbl,bkph,pbld)
            avail=SR.availability(cfg)
            revs=SR.reviews(cfg)
            bottom=B.get_bottom(cfg).get("total",{})
            out["clinics"][slug]={
                "by_source":by_src,"untagged_new":un_new,"untagged_repeat":un_rep,
                "lead_book":{"gmb_call":gmb_lb,
                    "gmb_web":{"leads":web["leads"],"booked":web["booked"],"notbooked":web["notbooked"]},
                    "gpaid_call":paid_lb,"gpaid_web":gpw,"practo":practo},
                "bottom":{"booked":bottom.get("booked",Z()),"done":bottom.get("done",Z()),
                          "purchased":bottom.get("purchased",Z()),"rev":bottom.get("rev",Z())},
                "reach":{},"reviews":revs,"avail":avail}
            if slug not in out["_meta"]["clinics"]: out["_meta"]["clinics"].append(slug)
            out["_meta"]["display"][slug]=cfg["disp"]
            ok+=1; print("[ok %d] %s (%d bk)"%(ok,cfg["disp"],cfg.get("bookings",0)), flush=True)
            if ok%3==0:  # incremental save so a crash never wastes progress
                json.dump(out,open(OUTPATH,"w"),separators=(",",":"))
        except BaseException as e:   # catch SystemExit from run_sql too → skip clinic, keep going
            fail+=1; print("[FAIL] %s: %s"%(cfg.get("disp",slug),type(e).__name__), flush=True)
    json.dump(out,open(OUTPATH,"w"),separators=(",",":"))
    print("wrote data_source_recon.json — %d built this run, %d failed, %d total clinics"%(ok,fail,len(out["clinics"])))

if __name__=="__main__":
    main()
