#!/usr/bin/env python3
"""Assemble Hadapsar clinic funnel → data_hadapsar.json (for hadapsar-funnel.html).

Combines, for Pune|Hadapsar, weekly (Monday, newest-first, 13 weeks):
  reach  — Google paid (location-asset, clinic-level, by category) + GMB (insights) + combined
  leads  — clinic CRM leads by channel + GMB call volume + AI call-audit category split
  bottom — booked / done / purchased / revenue × diagnosis category (exact Redshift)
Run: python3 scripts/assemble_hadapsar.py
"""
import os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K = "Pune|Hadapsar"
WEEKS = ["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11",
         "2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]
NW = len(WEEKS)

def L(f):
    try: return json.load(open(os.path.join(ROOT, f)))
    except Exception: return {}

def ctr(impr, clicks): return [round(clicks[i]/impr[i]*100,1) if impr[i] else None for i in range(NW)]

def add(a, b): return [(a[i] or 0)+(b[i] or 0) for i in range(NW)]

def main():
    geo    = L("data_hadapsar_google_geo.json")
    gmb    = (L("data_gmb_insights.json") or {}).get(K, {})
    cf     = (L("data_clinic_funnel.json") or {}).get("clinics", {}).get(K, {})
    bot    = L("data_hadapsar_bottom.json")
    practo = (L("data_practo_leads.json") or {}).get(K, {})
    calls  = L("data_hadapsar_calls.json")

    Z = [0]*NW
    def pad(lst): return (list(lst or []) + Z)[:NW]

    # Google paid (location asset)
    def _fit(a): a=a or []; return [(a[i] if i<len(a) and a[i] is not None else 0) for i in range(NW)]
    g_impr = _fit(geo.get("total",{}).get("impr")); g_clk = _fit(geo.get("total",{}).get("clicks"))
    gcats  = geo.get("by_cat") or {}

    # GMB
    gmb_impr = pad(gmb.get("searches"))
    gmb_calls_btn = pad(gmb.get("calls"))
    gmb_web  = pad(gmb.get("website"))
    gmb_dir  = pad(gmb.get("directions"))
    gmb_clk  = [(gmb_calls_btn[i] or 0)+(gmb_web[i] or 0)+(gmb_dir[i] or 0) for i in range(NW)]

    comb_impr = add(g_impr, gmb_impr); comb_clk = add(g_clk, gmb_clk)

    reach = {
        "google": {"impr": g_impr, "clicks": g_clk, "ctr": ctr(g_impr, g_clk),
                   "by_cat": {ct: {"impr": gcats[ct]["impr"], "clicks": gcats[ct]["clicks"],
                                   "ctr": gcats[ct]["ctr"]}
                              for ct in gcats} if gcats else {}},
        "gmb": {"impr": gmb_impr, "clicks": gmb_clk, "ctr": ctr(gmb_impr, gmb_clk),
                "calls": gmb_calls_btn, "website": gmb_web, "directions": gmb_dir},
        "combined": {"impr": comb_impr, "clicks": comb_clk, "ctr": ctr(comb_impr, comb_clk)},
    }

    lead = cf.get("lead", {}); bychan = lead.get("by_chan", {})
    bc = lambda k: (list(bychan.get(k) or []) + Z)[:NW]

    leads = {
        "total": (list(lead.get("leads_total") or []) + Z)[:NW],
        "by_chan": {
            "gmb":        bc("gmb"),
            "google_web": bc("google_ad"),
            "organic":    bc("organic"),
            "practo":     [(pad(practo.get("leads"))[i] or 0) + bc("practo_crm")[i] for i in range(NW)],
            "practo_sheet": pad(practo.get("leads")),
            "practo_crm": bc("practo_crm"),
            "fb":         bc("fb"),
            "other":      [bc("others")[i] + bc("justdial")[i] for i in range(NW)],
        },
        "raw": {k: (list(calls.get("raw", {}).get(k) or []) + Z)[:NW]
                for k in ("total", "unique", "answered", "missed")},
        "ai": {**(calls.get("gmb_ai") or calls.get("ai") or {"total":Z,"relevant":Z,"strong":Z,"by_cat":{}}),
               "calls": (calls.get("gmb_ai") or calls.get("ai") or {}).get("total", Z),
               "available": any((calls.get("gmb_ai") or calls.get("ai") or {}).get("total", []))},
        "paid_ai": calls.get("paid_ai") or {"total":Z,"relevant":Z,"strong":Z,"by_cat":{}},
    }

    bottom = {"total": bot.get("total", {}), "by_cat": bot.get("by_cat", {}),
              "cats": bot.get("_meta", {}).get("cats", [])}

    out = {"_meta": {"weeks": WEEKS, "clinic": K,
            "notes": {
                "google_reach": "Google paid impr/clicks for the Hadapsar location asset (clinic-level), by campaign category. Filtered to T1_/T2_ city-local campaigns. MH category = T1_Pune_MH_Exact_Local campaign.",
                "gmb": "GMB impr=searches, clicks=calls+website+directions. MH GMB change made ~May 25 2026.",
                "leads": "CRM leads by channel. raw = Exotel ground-truth for GMB number 2241483789 (DND-matching, 2× ratio confirmed). gmb_ai = AI category on GMB calls. paid_ai = Pune city-number calls where AI says caller mentioned Hadapsar.",
                "bottom": "booked/done/purchased/revenue by diagnosis. STI / SH (ED·PE·NSSD) / MH (from ICD-11 diagnoses) / Other. Hadapsar clinic = Savali_Allo_Clinic."}},
           "reach": reach, "leads": leads, "bottom": bottom}

    json.dump(out, open(os.path.join(ROOT, "data_hadapsar.json"), "w"), separators=(",", ":"))
    t = bottom["total"]
    print("wrote data_hadapsar.json")
    print(f"  reach latest: Google {g_impr[0]}impr/{g_clk[0]}clk · GMB {gmb_impr[0]}impr/{gmb_clk[0]}clk · combined CTR {reach['combined']['ctr'][0]}")
    print(f"  leads latest: total {leads['total'][0]} (gmb {leads['by_chan']['gmb'][0]} web {leads['by_chan']['google_web'][0]} org {leads['by_chan']['organic'][0]} practo {leads['by_chan']['practo'][0]})")
    if t: print(f"  bottom latest: booked {t.get('booked',[0])[0]} done {t.get('done',[0])[0]} purchased {t.get('purchased',[0])[0]} rev ₹{t.get('rev',[0])[0]:,}")

if __name__ == "__main__":
    main()
