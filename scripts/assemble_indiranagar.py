#!/usr/bin/env python3
"""Assemble the Indiranagar clinic funnel → data_indiranagar.json (one file for indiranagar-funnel.html).

Combines, for Bangalore|Indiranagar, weekly (Monday, newest-first, 12 weeks):
  reach   — Google paid (geo, clinic-level, by category) + GMB (insights) + combined; CTR each
  leads   — clinic CRM leads by channel (GMB/Google-web/Organic/Practo/FB/Other), raw GMB call
            volume, and the AI call-audit category split (STI/SH/MH/Other) where audited
  bottom  — booked / done / purchased / revenue, total + by diagnosis category (exact Redshift)

Sources (all pre-built): data_indiranagar_google_geo.json, data_gmb_insights.json,
  data_clinic_funnel.json, data_indiranagar_bottom.json, data_practo_leads.json.
Run:  python3 scripts/assemble_indiranagar.py     (no network — reads existing JSONs)
"""
import os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K = "Bangalore|Indiranagar"
WEEKS = ["2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04",
         "2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23"]
NW = len(WEEKS)

def L(f):
    try: return json.load(open(os.path.join(ROOT, f)))
    except Exception: return {}

def ctr(impr, clicks): return [round(clicks[i]/impr[i]*100,1) if impr[i] else None for i in range(NW)]
def add(a, b): return [(a[i] or 0)+(b[i] or 0) for i in range(NW)]

def main():
    geo = L("data_indiranagar_google_geo.json")
    gmb = (L("data_gmb_insights.json") or {}).get(K, {})
    cf  = (L("data_clinic_funnel.json") or {}).get("clinics", {}).get(K, {})
    bot = L("data_indiranagar_bottom.json")
    practo = (L("data_practo_leads.json") or {}).get(K, {})
    calls = L("data_indiranagar_calls.json")   # AI call audit: clinic-attributed calls by channel × category

    # ---- REACH ----
    g_impr = geo.get("total",{}).get("impr",[0]*NW); g_clk = geo.get("total",{}).get("clicks",[0]*NW)
    gmb_impr = gmb.get("searches",[0]*NW)
    gmb_calls = gmb.get("calls",[0]*NW); gmb_web = gmb.get("website",[0]*NW); gmb_dir = gmb.get("directions",[0]*NW)
    gmb_clk = [ (gmb_calls[i] or 0)+(gmb_web[i] or 0)+(gmb_dir[i] or 0) for i in range(NW) ]
    comb_impr = add(g_impr, gmb_impr); comb_clk = add(g_clk, gmb_clk)
    gcats = (geo.get("by_cat") or {})
    reach = {
        "google": {"impr": g_impr, "clicks": g_clk, "ctr": ctr(g_impr, g_clk),
                   "by_cat": {ct: {"impr": gcats[ct]["impr"], "clicks": gcats[ct]["clicks"], "ctr": gcats[ct]["ctr"]}
                              for ct in gcats}},
        "gmb": {"impr": gmb_impr, "clicks": gmb_clk, "ctr": ctr(gmb_impr, gmb_clk),
                "calls": gmb_calls, "website": gmb_web, "directions": gmb_dir},
        "combined": {"impr": comb_impr, "clicks": comb_clk, "ctr": ctr(comb_impr, comb_clk)},
    }

    # ---- LEADS (clinic CRM by channel + AI audit categories) ----
    lead = cf.get("lead", {}); bychan = lead.get("by_chan", {})
    Z = [0]*NW
    # bc: safe read from bychan — pads short arrays (12 wks) to NW with zeros
    bc = lambda k: (list(bychan.get(k) or []) + Z)[:NW]
    leads = {
        "total": lead.get("leads_total", Z),
        "by_chan": {
            "gmb":        bc("gmb"),
            "google_web": bc("google_ad"),
            "organic":    bc("organic"),
            "practo":     [ (practo.get("leads", Z)[i] or 0) + bc("practo_crm")[i] for i in range(NW) ],
            "practo_sheet": practo.get("leads", Z),
            "practo_crm": bc("practo_crm"),
            "outbound_wa": bc("outbound_wa"),
            "fb":         bc("fb"),
            "other":      [ bc("others")[i] + bc("justdial")[i] for i in range(NW) ],
        },
        "gmb_call_volume": lead.get("gmb_organic_calls", Z),     # raw GMB phone-call volume (context)
        "ai": {**(calls.get("total") or {"total":Z,"relevant":Z,"strong":Z,"by_cat":{}}),
               "calls": (calls.get("total") or {}).get("total", Z),
               "available": any((calls.get("total") or {}).get("total", []))},
        "call_channels": calls.get("channel", {}),               # #5: paid / gmb / other × category
    }

    # ---- BOTTOM (exact) ----
    bottom = {"total": bot.get("total", {}), "by_cat": bot.get("by_cat", {}), "cats": bot.get("_meta",{}).get("cats",[])}

    out = {"_meta": {"weeks": WEEKS, "clinic": K,
            "notes": {
                "google_reach": "Google paid impr/clicks for users physically in Indiranagar (geographic_view location-of-presence) — clinic-level, by campaign category. Real, not estimated.",
                "paid_calls": "Paid Google calls ride a shared city number, BUT the AI call audit resolves the clinic the caller wanted (locality intent), so AI-audited call leads ARE clinic-attributed — incl. paid calls.",
                "gmb": "GMB impr=searches, clicks=calls+website+directions (Google Business Profile, this clinic). GMB reach itself has no category.",
                "leads": "Clinic CRM leads by channel (deduped). gmb_call_volume = raw GMB phone-call count (context). AI call-audit layer = inbound call leads attributed to this clinic by intent and split by category (STI/SH/MH/Other), with relevant/strong intent; bucketed by call time (covers ~late-Apr on).",
                "bottom": "booked/done/purchased/revenue exact from Redshift; category = consultation diagnosis (STI/ED+/PE+/ED+PE+/NSSD/oth)."}},
        "reach": reach, "leads": leads, "bottom": bottom}
    json.dump(out, open(os.path.join(ROOT, "data_indiranagar.json"), "w"), separators=(",", ":"))
    t = bottom["total"]
    print("wrote data_indiranagar.json")
    print(f"  reach latest: Google {g_impr[0]}impr/{g_clk[0]}clk · GMB {gmb_impr[0]}impr/{gmb_clk[0]}clk · combined CTR {reach['combined']['ctr'][0]}")
    print(f"  leads latest: total {leads['total'][0]} (gmb {leads['by_chan']['gmb'][0]} web {leads['by_chan']['google_web'][0]} org {leads['by_chan']['organic'][0]} practo {leads['by_chan']['practo'][0]})")
    if t: print(f"  bottom latest: booked {t['booked'][0]} done {t['done'][0]} purchased {t['purchased'][0]} rev ₹{t['rev'][0]:,}")

if __name__ == "__main__":
    main()
