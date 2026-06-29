#!/usr/bin/env python3
"""Per-clinic ORGANIC call funnel: inbound lead calls (routed_to=lead_to_call) on
numbers that are NOT a GMB-listing or Google-paid number — i.e. website/Practo/direct
calls. Attributed to the clinic via the AI call-audit's locality (best_match), like
paid. Writes lead_book.organic_call = {total,answered,missed,relevant,booked} (clinic
locality-matched). Resumable. Run: AWS_PROFILE=redshift-data python3 scripts/patch_organic_calls.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import build_clinic_wow as W
import build_source_recon as SR
OUT = os.path.join(W.ROOT, "data_source_recon.json"); idx = SR.idx; NW = SR.NW; Z = lambda: [0]*NW
LO = SR.LO; run_sql = SR.run_sql; REL = SR.REL
CFG = W.CFG
# all GMB + paid numbers across clinics -> excluded from organic
KNOWN = set()
for c in CFG.values():
    for g in (c.get("gmb") or []): KNOWN.add(g[-10:])
    if c.get("paid"): KNOWN.add(c["paid"][-10:])
KNOWN_LIST = "','".join(sorted(KNOWN))

def organic_sql(cfg):
    loc = cfg["loc"].replace("'", "''"); city = cfg["city"].replace("'", "''")
    return """WITH calls AS (
      SELECT ec.call_id, RIGHT(ec."from",10) ph, ec.status,
        TO_CHAR(DATE_TRUNC('week', ec.start_time+INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk
      FROM allo_vendors.exotel_calls ec
      WHERE ec.direction='inbound' AND ec.routed_to='lead_to_call'
        AND RIGHT(ec.exotel_number,10) NOT IN ('{known}')
        AND (ec.start_time+INTERVAL '5 hours 30 minutes')>='{lo}' AND (ec.start_time+INTERVAL '5 hours 30 minutes')<'2026-06-29'),
     aud AS (SELECT ca.call_id,
        MAX(CASE WHEN ca.analysis.user_intent.result::varchar IN ({rel}) THEN 1 ELSE 0 END) rel,
        MAX(CASE WHEN ca.analysis.user_intent.locality_mentioned.is_our_locality=true
            AND ca.analysis.user_intent.locality_mentioned.best_match::varchar='{loc}' THEN 1 ELSE 0 END) locok
       FROM allo_analytics.call_analyses ca WHERE ca.deleted_at IS NULL GROUP BY 1),
     bk AS (SELECT DISTINCT RIGHT(p.phone_no,10) ph FROM allo_consultations.appointments a
       JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.city='{city}' AND loc.locality='{loc}' AND loc.deleted_at IS NULL
       JOIN allo_persons.patient p ON p.id=a.patient_id
       JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
       WHERE a.deleted_at IS NULL AND a.created_at>='2025-06-23')
    SELECT calls.wk,
      COUNT(DISTINCT CASE WHEN aud.locok=1 THEN calls.ph END) total,
      COUNT(DISTINCT CASE WHEN aud.locok=1 AND calls.status='completed' THEN calls.ph END) answered,
      COUNT(DISTINCT CASE WHEN aud.locok=1 AND calls.status<>'completed' THEN calls.ph END) missed,
      COUNT(DISTINCT CASE WHEN aud.rel=1 AND aud.locok=1 THEN calls.ph END) relevant,
      COUNT(DISTINCT CASE WHEN aud.rel=1 AND aud.locok=1 AND bk.ph IS NOT NULL THEN calls.ph END) booked
    FROM calls LEFT JOIN aud ON aud.call_id=calls.call_id LEFT JOIN bk ON bk.ph=calls.ph
    GROUP BY 1;""".format(known=KNOWN_LIST, rel=REL, lo=LO, loc=loc, city=city)

def organic(cfg):
    d = {k: Z() for k in ("total","answered","missed","relevant","booked")}
    for line in run_sql(organic_sql(cfg)):
        c = line.split("\t")
        if len(c) < 6 or c[0] not in idx: continue
        i = idx[c[0]]
        try:
            for k, j in (("total",1),("answered",2),("missed",3),("relevant",4),("booked",5)):
                d[k][i] = int(float(c[j]))
        except ValueError: pass
    d["notbooked"] = [d["relevant"][i]-d["booked"][i] for i in range(NW)]
    return d

if __name__ == "__main__":
    dd = json.load(open(OUT)); done = 0
    items = list(dd["clinics"].items())
    for slug, c in items:
        if (c.get("lead_book", {}) or {}).get("organic_call"): continue
        cfg = CFG.get(slug)
        if not cfg: continue
        try:
            oc = organic(cfg); c.setdefault("lead_book", {})["organic_call"] = oc; done += 1
            print("[ok %d] %s  organic leads=%d" % (done, cfg["disp"], sum(oc["total"])), flush=True)
            if done % 5 == 0: json.dump(dd, open(OUT,"w"), separators=(",",":"))
        except BaseException as e:
            print("[FAIL] %s: %s" % (cfg.get("disp", slug), type(e).__name__), flush=True)
    json.dump(dd, open(OUT,"w"), separators=(",",":"))
    print("ORGANIC_DONE patched %d" % done, flush=True)
