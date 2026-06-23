#!/usr/bin/env python3
"""LIVE Google Ads → data_mh_<slug>_google_geo.json for MH clinics that lacked geo.

Same location-asset performance report as pull_hadapsar_google_asset.py, generalised:
 • single-clinic cities (Coimbatore→Bharathi, Jaipur→Vaishali, Hubballi→Hubli):
   city == clinic, so sum ALL T1_/T2_<city> location-asset impressions (no place_id needed).
 • multi-clinic cities without a resolved place_id (Navi Mumbai→Kharghar, Pune→Kharadi):
   city-level paid reach, flagged shared (per-clinic asset isolation pending place_id).
Indiranagar + Hadapsar already have precise place_id geo and are skipped.
16-week window to match build_mh_funnels. Run: source ~/.allo_google_ads.env && python3 scripts/pull_mh_google_assets.py
"""
import os, json, sys, re, datetime
sys.path.insert(0, os.path.dirname(__file__))
from pull_hadapsar_google_asset import _creds, _token, gaql, cat_of, CATS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKS = ["2026-06-22","2026-06-15","2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11",
         "2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23",
         "2026-03-16","2026-03-09"]
widx = {w: i for i, w in enumerate(WEEKS)}; NW = len(WEEKS)

# slug → (city campaign token, shared?)  — token matches the T1_<token>_ campaign-name prefix
CLINICS = {
    "bharathi": ("Coimbatore", False),
    "vaishali": ("Jaipur",     False),
    "hubli":    ("Hubballi",   False),
    "kharghar": ("Navi",       True),
    "kharadi":  ("Pune",       True),
}

def main():
    c = _creds(); token = _token(c)
    start = datetime.date.fromisoformat(WEEKS[-1])
    end = datetime.date.fromisoformat(WEEKS[0]) + datetime.timedelta(days=6)
    ymd = lambda d: d.strftime("%Y-%m-%d")

    rows = gaql(token, c, f"""
      SELECT campaign.name, segments.week,
        segments.asset_interaction_target.asset, segments.asset_interaction_target.interaction_on_this_asset,
        metrics.impressions, metrics.clicks
      FROM campaign
      WHERE campaign.advertising_channel_type = SEARCH AND campaign.status = ENABLED
        AND segments.date BETWEEN '{ymd(start)}' AND '{ymd(end)}'""")

    def Z(): return {m: [0]*NW for m in ('impr','clicks')}
    ctr = lambda dd: [round(dd['clicks'][i]/dd['impr'][i]*100,1) if dd['impr'][i] else None for i in range(NW)]

    for slug, (tok, shared) in CLINICS.items():
        bycat = {ct: Z() for ct in CATS}; tot = Z()
        pref = (f"T1_{tok}", f"T2_{tok}")
        for r in rows:
            name = r["campaign"]["name"]
            if not name.startswith(pref): continue
            seg = r["segments"]; ait = seg.get("assetInteractionTarget") or {}
            if not ait.get("asset"): continue          # location-asset rows only
            wk = seg.get("week")
            if wk not in widx: continue
            i = widx[wk]; ct = cat_of(name); m = r.get("metrics", {})
            clk = int(m.get("clicks",0) or 0); imp = int(m.get("impressions",0) or 0)
            bycat[ct]['clicks'][i] += clk; tot['clicks'][i] += clk
            if not ait.get("interactionOnThisAsset", False):
                bycat[ct]['impr'][i] += imp; tot['impr'][i] += imp
        out = {"_meta": {"weeks": WEEKS, "city_token": tok, "shared": shared,
                "source": "LIVE Google Ads · location-asset performance, summed over T1_/T2_%s city-local campaigns" % tok,
                "note": ("Single-clinic city — city paid reach == this clinic's location-asset reach."
                         if not shared else
                         "Multi-clinic city — CITY-LEVEL paid reach (shared across the city's clinics); per-clinic asset isolation pending place_id.")},
            "total": {**tot, "ctr": ctr(tot)},
            "by_cat": {ct: {**bycat[ct], "ctr": ctr(bycat[ct])} for ct in CATS}}
        json.dump(out, open(os.path.join(ROOT, f"data_mh_{slug}_google_geo.json"), "w"), separators=(",", ":"))
        print(f"[{slug}] T1_{tok} {'(shared)' if shared else '(single)'}: impr wk1 {tot['impr'][1]} clk {tot['clicks'][1]} | "
              + " ".join(f"{ct} {bycat[ct]['impr'][1]}i" for ct in CATS if bycat[ct]['impr'][1]))

if __name__ == "__main__":
    main()
