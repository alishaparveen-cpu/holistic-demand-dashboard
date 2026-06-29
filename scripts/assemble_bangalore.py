#!/usr/bin/env python3
"""Assemble the Bangalore CITY funnel → data_bangalore.json (one file for bangalore.html),
in the SAME shape as data_indiranagar.json so the clinic-page render works unchanged.

City = sum of all 14 Bangalore clinics, weekly (Mon, newest-first, 12wk):
  reach   — Google paid (data_ga_city_paid Bangalore: real city-level impr/clicks) + GMB
            (summed across the 14 clinic Business-Profiles); combined; CTR each.
            NOTE: Google-by-category is NOT available citywide (only per-clinic location assets
            carry it, and we only hold Indiranagar's place_id) — so reach has no category split.
            Category lives where it's real: the AI call audit, lead buckets, and diagnosis.
  leads   — summed clinic CRM leads by channel + summed GMB call volume + the citywide AI
            call-audit category split (STI/SH/MH/Other) from data_bangalore_calls.json
  bottom  — booked/done/purchased/revenue, total + by diagnosis, from data_bangalore_bottom.json
Run:  python3 scripts/assemble_bangalore.py     (no network — reads existing JSONs)
"""
import os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKS = ["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11",
         "2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30"]
NW = len(WEEKS); Z = [0]*NW

def L(f):
    try: return json.load(open(os.path.join(ROOT, f)))
    except Exception: return {}
def ctr(impr, clicks): return [round(clicks[i]/impr[i]*100,1) if impr[i] else None for i in range(NW)]
def add(a, b): return [(a[i] or 0)+(b[i] or 0) for i in range(NW)]
def fit(a):  # coerce any list to NW length (pad/truncate), Nones→0-safe later
    a = a or []
    return [ (a[i] if i < len(a) and a[i] is not None else 0) for i in range(NW) ]

def main():
    gmb_all = L("data_gmb_insights.json")
    cf      = (L("data_clinic_funnel.json") or {}).get("clinics", {})
    practo  = L("data_practo_leads.json")
    citypaid= (L("data_ga_city_paid.json") or {}).get("Bangalore", {})
    calls   = L("data_bangalore_calls.json")
    bot     = L("data_bangalore_bottom.json")
    BLR = [k for k in cf if k.startswith("Bangalore|")]

    # ---- REACH ----
    g_impr = fit(citypaid.get("impr", Z)); g_clk = fit(citypaid.get("clicks", Z))
    gmb_impr = Z[:]; gmb_calls = Z[:]; gmb_web = Z[:]; gmb_dir = Z[:]
    for k, v in gmb_all.items():
        if not k.startswith("Bangalore|"): continue
        gmb_impr = add(gmb_impr, fit(v.get("searches", Z)))
        gmb_calls = add(gmb_calls, fit(v.get("calls", Z)))
        gmb_web  = add(gmb_web,  fit(v.get("website", Z)))
        gmb_dir  = add(gmb_dir,  fit(v.get("directions", Z)))
    gmb_clk = [ gmb_calls[i]+gmb_web[i]+gmb_dir[i] for i in range(NW) ]
    comb_impr = add(g_impr, gmb_impr); comb_clk = add(g_clk, gmb_clk)
    reach = {
        "google": {"impr": g_impr, "clicks": g_clk, "ctr": ctr(g_impr, g_clk), "by_cat": {}},
        "gmb": {"impr": gmb_impr, "clicks": gmb_clk, "ctr": ctr(gmb_impr, gmb_clk),
                "calls": gmb_calls, "website": gmb_web, "directions": gmb_dir},
        "combined": {"impr": comb_impr, "clicks": comb_clk, "ctr": ctr(comb_impr, comb_clk)},
    }

    # ---- LEADS (summed clinic CRM channels + citywide AI audit) ----
    tot = Z[:]; gmb=Z[:]; gweb=Z[:]; org=Z[:]; fb=Z[:]; oth=Z[:]; pr=Z[:]; gcv=Z[:]
    for k in BLR:
        lead = cf[k].get("lead", {}); bc = lead.get("by_chan", {})
        tot  = add(tot,  fit(lead.get("leads_total", Z)))
        gmb  = add(gmb,  fit(bc.get("gmb", Z)))
        gweb = add(gweb, fit(bc.get("google_ad", Z)))
        org  = add(org,  fit(bc.get("organic", Z)))
        fb   = add(fb,   fit(bc.get("fb", Z)))
        oth  = add(oth,  add(fit(bc.get("others", Z)), fit(bc.get("justdial", Z))))
        gcv  = add(gcv,  fit(lead.get("gmb_organic_calls", Z)))
        pr   = add(pr,   fit((practo.get(k, {}) or {}).get("leads", Z)))
    ai_t = (calls.get("total") or {})
    leads = {
        "total": tot,
        "by_chan": {"gmb": gmb, "google_web": gweb, "organic": org, "practo": pr, "fb": fb, "other": oth},
        "gmb_call_volume": gcv,
        "ai": {"total": ai_t.get("total", Z), "relevant": ai_t.get("relevant", Z), "strong": ai_t.get("strong", Z),
               "by_cat": ai_t.get("by_cat", {}), "relevant_by_cat": ai_t.get("relevant_by_cat", {}),
               "calls": ai_t.get("total", Z), "available": any(ai_t.get("total", []))},
        "call_channels": calls.get("channel", {}),
    }

    # ---- BOTTOM (city, exact) ----
    cbot = bot.get("city", {})
    bottom = {"total": cbot.get("total", {}), "by_cat": cbot.get("by_cat", {}),
              "cats": bot.get("_meta", {}).get("cats", ["STI","SH","Other"])}

    out = {"_meta": {"weeks": WEEKS, "city": "Bangalore", "n_clinics": len(BLR), "clinics": sorted(BLR),
            "notes": {
              "google_reach": "Google paid impr/clicks at CITY level (data_ga_city_paid, location-of-presence = Bangalore). Real, not estimated. No category split citywide (only per-clinic location assets carry category, and only Indiranagar's place_id is held).",
              "gmb": "GMB impr=searches, clicks=calls+website+directions — summed across all 14 Bangalore Business Profiles.",
              "leads": "Clinic CRM leads by channel, SUMMED across the 14 clinics. AI call-audit layer = citywide inbound call leads by intent and category (STI/SH/MH/Other) — CALL VOLUME, does not reconcile.",
              "bottom": "Booked/Done/Purchased/Revenue, city = sum of all 14 clinic funnels (data_bangalore_bottom). Category = consultation diagnosis (STI / SH / Other); MH has no diagnosis tag so it sits in Other."}},
        "reach": reach, "leads": leads, "bottom": bottom}
    json.dump(out, open(os.path.join(ROOT, "data_bangalore.json"), "w"), separators=(",", ":"))
    i = 0
    print(f"wrote data_bangalore.json · {len(BLR)} clinics")
    print(f"  reach wk0: Google {g_impr[i]} impr / {g_clk[i]} clk · GMB {gmb_impr[i]} / {gmb_clk[i]} · combined {comb_impr[i]} / {comb_clk[i]}")
    print(f"  leads wk0: total {tot[i]} (gmb {gmb[i]} · g-web {gweb[i]} · organic {org[i]} · practo {pr[i]} · fb {fb[i]} · other {oth[i]})")
    print(f"  bottom wk0: booked {bottom['total'].get('booked',[0])[i]} done {bottom['total'].get('done',[0])[i]} rev {bottom['total'].get('rev',[0])[i]}")

if __name__ == "__main__":
    main()
