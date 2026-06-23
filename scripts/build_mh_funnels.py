#!/usr/bin/env python3
"""Build full Hadapsar-style funnel data for every MH clinic → data_mh_<slug>.json.

Same JSON shape as data_hadapsar.json so one template (mh-funnel.html) renders any
clinic via a dropdown. Per clinic, from Redshift + shared JSONs:
  reach  — GMB insights (data_gmb_insights) + Google location-asset geo if a
           data_<slug>_google_geo.json exists (Indiranagar); else empty by_cat.
  leads  — CRM by channel (data_clinic_funnel)
  calls  — raw + AI-audit (STI/SH/MH/Other) on the clinic-direct GMB number(s),
           unioning the dedicated MH listing line where one exists; paid_ai on the
           shared city Google call-asset where known.
  bottom — booked/done/purchased/revenue × STI/SH/MH/Other (MH via ICD-11 diagnoses).
Run: AWS_PROFILE=redshift-data python3 scripts/build_mh_funnels.py
"""
import os, sys, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11",
         "2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23",
         "2026-03-16","2026-03-09"]
idx = {w: i for i, w in enumerate(WEEKS)}; NW = len(WEEKS)
LO = "2026-03-02"   # SQL lower bound (a bit before the oldest week)
AUDIT_START = "2026-03-23"   # AI call-audit (call_analyses) reaches coverage here; earlier weeks have ~none
# MH launch per clinic — Monday of the launch week, + label (doctor + date)
LAUNCH = {
  "bharathi":    ("2026-03-09", "Mar · Dr. Sandhiya"),
  "indiranagar": ("2026-03-30", "1 Apr · Dr. Adithya + Dr. Chetan"),
  "vaishali":    ("2026-05-18", "22 May · Dr. Ashish"),
  "hadapsar":    ("2026-05-18", "22 May · Dr. Pragnya"),
  "hubli":       ("2026-06-01", "5 Jun · Dr. Varsha"),
  "kharghar":    ("2026-06-08", "12 Jun · Dr. Reeva"),
  "kharadi":     ("2026-06-15", "20 Jun · Dr. Shaunak"),
}
CATS = ["STI", "SH", "MH", "Other"]
CATMAP = {"STI":"STI","SEXUAL_HEALTH_GENERAL":"SH","MENTAL_HEALTH":"MH","OTHER":"Other","NOT_MENTIONED":"Other"}
RELEVANT = ("TALK_TO_DOCTOR","NEEDS_TESTS","BOOK_APPOINTMENT","BOOK_TEST","BOOK_SLOT")

# slug → config. gmb = clinic-direct GMB listing number(s) (main + dedicated MH line).
CLINICS = {
  "bharathi":    {"key":"Coimbatore|Bharathi Nagar","disp":"Bharathi Nagar · Coimbatore","city":"Coimbatore","loc":"Bharathi Nagar","gmb":["4440114608","4440116568"],"paid":None,"geo":"data_mh_bharathi_google_geo.json"},
  "indiranagar": {"key":"Bangalore|Indiranagar","disp":"Indiranagar · Bangalore","city":"Bangalore","loc":"Indiranagar","gmb":["8047160881","8047281164"],"paid":"8045680561","geo":"data_indiranagar_google_geo.json"},
  "vaishali":    {"key":"Jaipur|Vaishali Nagar","disp":"Vaishali Nagar · Jaipur","city":"Jaipur","loc":"Vaishali Nagar","gmb":["1414931073"],"paid":None,"geo":"data_mh_vaishali_google_geo.json"},
  "hadapsar":    {"key":"Pune|Hadapsar","disp":"Hadapsar · Pune","city":"Pune","loc":"Hadapsar","gmb":["2241483789"],"paid":"2048556242","geo":"data_hadapsar_google_geo.json"},
  "kharghar":    {"key":"Navi Mumbai|Kharghar","disp":"Kharghar · Navi Mumbai","city":"Navi Mumbai","loc":"Kharghar","gmb":["2248932451"],"paid":None,"geo":"data_mh_kharghar_google_geo.json"},
  "hubli":       {"key":"Hubli|Vidya Nagar","disp":"Vidya Nagar · Hubli","city":"Hubli","loc":"Vidya Nagar","gmb":["8047094835"],"paid":None,"geo":"data_mh_hubli_google_geo.json"},
  "kharadi":     {"key":"Pune|Kharadi","disp":"Kharadi · Pune","city":"Pune","loc":"Kharadi","gmb":["2241484446"],"paid":"2048556242","geo":"data_mh_kharadi_google_geo.json"},
}

def run_sql(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("query failed: " + (p.stderr or "")[:500] + "\n"); sys.exit(1)
    return p.stdout.strip().splitlines()

def L(f):
    try: return json.load(open(os.path.join(ROOT, f)))
    except Exception: return {}

Z = [0]*NW
def pad(a): return (list(a or []) + Z)[:NW]
def add(a, b): return [(a[i] or 0)+(b[i] or 0) for i in range(NW)]
def ctr(impr, clicks): return [round(clicks[i]/impr[i]*100,1) if impr[i] else None for i in range(NW)]

# ---------- bottom ----------
def bottom_sql(city, loc):
    return """WITH loc AS (SELECT id FROM allo_health.locations WHERE deleted_at IS NULL AND city='{city}' AND locality='{loc}'),
  enc_tag AS (
    SELECT e.appointment_id ap_id,
      CASE WHEN MAX(CASE WHEN et.tag_type='sti' THEN 1 ELSE 0 END)=1 THEN 'STI'
           WHEN MAX(CASE WHEN et.tag_type IN ('ed_plus_pe_plus','ed_plus','pe_plus','nssd') THEN 1 ELSE 0 END)=1 THEN 'SH'
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
  ap0 AS (
    SELECT a.id, a.patient_id, TO_CHAR(DATE_TRUNC('week', a.created_at + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk, a.status
    FROM allo_consultations.appointments a JOIN allo_consultations.types typ ON typ.id=a.type_id AND typ.name='Screening Call'
    JOIN loc ON loc.id=a.location_id WHERE a.created_at >= '2026-03-02' AND a.deleted_at IS NULL),
  ap AS (SELECT id, wk, status FROM (SELECT ap0.*, ROW_NUMBER() OVER (PARTITION BY patient_id, wk
      ORDER BY (CASE WHEN status='COMPLETED' THEN 0 ELSE 1 END), id) rn FROM ap0) z WHERE rn=1),
  inv AS (SELECT e.appointment_id ap_id, SUM(i.amount) amt FROM allo_encounters.encounters e
    JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.deleted_at IS NULL AND i.status='paid' WHERE e.deleted_at IS NULL GROUP BY 1)
  SELECT ap.wk,
    CASE WHEN COALESCE(et.tag_cat,'oth')='STI' THEN 'STI' WHEN COALESCE(et.tag_cat,'oth')='SH' THEN 'SH'
         WHEN mh.ap_id IS NOT NULL THEN 'MH' ELSE 'Other' END cat,
    COUNT(*) booked, SUM(CASE WHEN ap.status='COMPLETED' THEN 1 ELSE 0 END) done,
    COUNT(CASE WHEN ap.status='COMPLETED' AND inv.ap_id IS NOT NULL THEN 1 END) purchased,
    SUM(CASE WHEN ap.status='COMPLETED' THEN COALESCE(inv.amt,0) ELSE 0 END) rev_paise
  FROM ap LEFT JOIN enc_tag et ON et.ap_id=ap.id LEFT JOIN mh_ap mh ON mh.ap_id=ap.id LEFT JOIN inv ON inv.ap_id=ap.id
  GROUP BY 1,2 ORDER BY 1,2;""".format(city=city.replace("'","''"), loc=loc.replace("'","''"))

def get_bottom(cfg):
    FIELDS = ("booked","done","purchased","rev")
    def blank(): return {k:[0]*NW for k in FIELDS}
    bycat = {c: blank() for c in CATS}; tot = blank()
    for line in run_sql(bottom_sql(cfg["city"], cfg["loc"])):
        c = line.split("\t")
        if len(c) < 6 or c[0] not in idx: continue
        wk, cat = c[0], c[1]
        if cat not in CATS: cat = "Other"
        i = idx[wk]
        try: bk,dn,pu,rp = int(c[2]),int(c[3]),int(c[4]),int(float(c[5]))
        except ValueError: continue
        rev = round(rp/100.0)
        for tgt in (bycat[cat], tot):
            tgt["booked"][i]+=bk; tgt["done"][i]+=dn; tgt["purchased"][i]+=pu; tgt["rev"][i]+=rev
    return {"total": tot, "by_cat": bycat, "cats": CATS}

# ---------- calls (raw + gmb_ai + paid_ai) ----------
def get_calls(cfg):
    nums = "','".join(cfg["gmb"])
    raw_sql = """SELECT TO_CHAR(DATE_TRUNC('week', ec.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk,
      COUNT(*) total, COUNT(DISTINCT RIGHT(COALESCE(ec."from",''),10)) uniq,
      SUM(CASE WHEN ec.status='completed' THEN 1 ELSE 0 END) answered,
      SUM(CASE WHEN ec.status!='completed' THEN 1 ELSE 0 END) missed
    FROM allo_vendors.exotel_calls ec WHERE RIGHT(ec.exotel_number,10) IN ('{nums}')
      AND ec.routed_to='lead_to_call' AND (ec.start_time + INTERVAL '5 hours 30 minutes') >= '2026-03-02'
    GROUP BY 1;""".format(nums=nums)
    ai_sql = """SELECT TO_CHAR(DATE_TRUNC('week', ec.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk,
      COALESCE(ca.analysis.diagnoses.category::varchar,'NOT_MENTIONED') cat,
      ca.analysis.user_intent.result::varchar intent, ca.analysis.patient_intent_strength.result::varchar strength, COUNT(*) n
    FROM allo_analytics.call_analyses ca JOIN allo_vendors.exotel_calls ec ON ec.call_id=ca.call_id AND ec.routed_to='lead_to_call'
    WHERE ca.deleted_at IS NULL AND RIGHT(ec.exotel_number,10) IN ('{nums}')
      AND (ec.start_time + INTERVAL '5 hours 30 minutes') >= '2026-03-02' GROUP BY 1,2,3,4;""".format(nums=nums)
    raw = {"total":list(Z),"unique":list(Z),"answered":list(Z),"missed":list(Z)}
    for line in run_sql(raw_sql):
        c = line.split("\t")
        if len(c) < 5 or c[0] not in idx: continue
        i = idx[c[0]]
        try: raw["total"][i]=int(float(c[1])); raw["unique"][i]=int(float(c[2])); raw["answered"][i]=int(float(c[3])); raw["missed"][i]=int(float(c[4]))
        except ValueError: pass
    def blank_ai(): return {"total":[0]*NW,"relevant":[0]*NW,"strong":[0]*NW,"by_cat":{c:[0]*NW for c in CATS}}
    gmb_ai = blank_ai()
    for line in run_sql(ai_sql):
        c = line.split("\t")
        if len(c) < 5 or c[0] not in idx: continue
        wk, rawcat, intent, strength, n_s = c
        try: n=int(float(n_s))
        except ValueError: continue
        i = idx[wk]; cat = CATMAP.get(rawcat,"Other")
        gmb_ai["total"][i]+=n; gmb_ai["by_cat"][cat][i]+=n
        if intent in RELEVANT: gmb_ai["relevant"][i]+=n
        if strength=="STRONG": gmb_ai["strong"][i]+=n
    paid_ai = blank_ai()
    if cfg["paid"]:
        paid_sql = """SELECT TO_CHAR(DATE_TRUNC('week', ec.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk,
          COALESCE(ca.analysis.diagnoses.category::varchar,'NOT_MENTIONED') cat, ca.analysis.user_intent.result::varchar intent, COUNT(*) n
        FROM allo_analytics.call_analyses ca JOIN allo_vendors.exotel_calls ec ON ec.call_id=ca.call_id AND ec.routed_to='lead_to_call'
        WHERE ca.deleted_at IS NULL AND RIGHT(ec.exotel_number,10)='{paid}'
          AND ca.analysis.user_intent.locality_mentioned.is_our_locality=true
          AND ca.analysis.user_intent.locality_mentioned.best_match::varchar='{loc}'
          AND (ec.start_time + INTERVAL '5 hours 30 minutes') >= '2026-03-02' GROUP BY 1,2,3;""".format(paid=cfg["paid"], loc=cfg["loc"].replace("'","''"))
        for line in run_sql(paid_sql):
            c = line.split("\t")
            if len(c) < 4 or c[0] not in idx: continue
            wk, rawcat, intent, n_s = c
            try: n=int(float(n_s))
            except ValueError: continue
            i = idx[wk]; cat = CATMAP.get(rawcat,"Other")
            paid_ai["total"][i]+=n; paid_ai["by_cat"][cat][i]+=n
            if intent in RELEVANT: paid_ai["relevant"][i]+=n
    # AI call-audit (call_analyses) only reaches coverage from AUDIT_START; blank earlier
    # weeks to None so they render "—" (not a misleading 0). raw exotel volume stays real.
    pre = [i for i, w in enumerate(WEEKS) if w < AUDIT_START]
    for d in (gmb_ai, paid_ai):
        for i in pre:
            d["total"][i] = None; d["relevant"][i] = None; d["strong"][i] = None
            for c in CATS: d["by_cat"][c][i] = None
    return raw, gmb_ai, paid_ai

def assemble(slug, cfg):
    bottom = get_bottom(cfg)
    raw, gmb_ai, paid_ai = get_calls(cfg)
    gmb = (L("data_gmb_insights.json") or {}).get(cfg["key"], {})
    cf  = (L("data_clinic_funnel.json") or {}).get("clinics", {}).get(cfg["key"], {})
    practo = (L("data_practo_leads.json") or {}).get(cfg["key"], {})
    geo = L(cfg["geo"]) if cfg["geo"] else {}

    gmb_impr = pad(gmb.get("searches")); gmb_calls = pad(gmb.get("calls")); gmb_web = pad(gmb.get("website")); gmb_dir = pad(gmb.get("directions"))
    gmb_clk = [gmb_calls[i]+gmb_web[i]+gmb_dir[i] for i in range(NW)]
    g_impr = pad((geo.get("total") or {}).get("impr")); g_clk = pad((geo.get("total") or {}).get("clicks"))
    gcats = geo.get("by_cat") or {}
    comb_impr = add(g_impr, gmb_impr); comb_clk = add(g_clk, gmb_clk)
    reach = {
        "google": {"impr": g_impr, "clicks": g_clk, "ctr": ctr(g_impr, g_clk),
                   "by_cat": {ct: {"impr": pad(gcats[ct].get("impr")), "clicks": pad(gcats[ct].get("clicks")), "ctr": gcats[ct].get("ctr")} for ct in gcats} if gcats else {}},
        "gmb": {"impr": gmb_impr, "clicks": gmb_clk, "ctr": ctr(gmb_impr, gmb_clk), "calls": gmb_calls, "website": gmb_web, "directions": gmb_dir},
        "combined": {"impr": comb_impr, "clicks": comb_clk, "ctr": ctr(comb_impr, comb_clk)},
    }
    lead = cf.get("lead", {}); bychan = lead.get("by_chan", {})
    bc = lambda k: pad(bychan.get(k))
    leads = {
        "total": pad(lead.get("leads_total")),
        "by_chan": {"gmb": bc("gmb"), "google_web": bc("google_ad"), "organic": bc("organic"),
                    "practo": [(pad(practo.get("leads"))[i] or 0)+bc("practo_crm")[i] for i in range(NW)],
                    "practo_sheet": pad(practo.get("leads")), "practo_crm": bc("practo_crm"),
                    "fb": bc("fb"), "other": [bc("others")[i]+bc("justdial")[i] for i in range(NW)]},
        "raw": raw,
        "ai": {**gmb_ai, "calls": gmb_ai["total"], "available": any(gmb_ai["total"])},
        "paid_ai": paid_ai,
    }
    lw = LAUNCH.get(slug)
    out = {"_meta": {"weeks": WEEKS, "clinic": cfg["key"], "display": cfg["disp"], "city": cfg["city"], "locality": cfg["loc"],
            "gmb_number": cfg["gmb"][0], "mh_number": (cfg["gmb"][1] if len(cfg["gmb"])>1 else None), "paid_number": cfg["paid"],
            "mh_launch": (lw[0] if lw else None), "mh_launch_label": (lw[1] if lw else None),
            "audit_start": AUDIT_START,
            "has_google_cat": bool(gcats), "google_shared": bool((geo.get("_meta") or {}).get("shared")),
            "note": "MH funnel. bottom: STI/SH via encounter_tags, MH via ICD-11 diagnoses (6A-6E/keywords), no STI/SH tag. calls: AI audit on clinic-direct GMB number(s) incl dedicated MH line; paid_ai on shared city Google call-asset where known."},
        "reach": reach, "leads": leads, "bottom": bottom}
    json.dump(out, open(os.path.join(ROOT, "data_mh_%s.json" % slug), "w"), separators=(",", ":"))
    t = bottom["total"]; bc2 = bottom["by_cat"]
    print(f"[{slug}] {cfg['disp']}: booked {t['booked'][1]} done {t['done'][1]} | done STI {bc2['STI']['done'][1]} SH {bc2['SH']['done'][1]} MH {bc2['MH']['done'][1]} Oth {bc2['Other']['done'][1]} | gmb_ai wk1 total {gmb_ai['total'][1]} MH {gmb_ai['by_cat']['MH'][1]} | paid_ai {sum(x or 0 for x in paid_ai['total'])}")

def main():
    for slug, cfg in CLINICS.items():
        assemble(slug, cfg)
    print("done — data_mh_{bharathi,indiranagar,krpuram,vaishali}.json")

if __name__ == "__main__":
    main()
