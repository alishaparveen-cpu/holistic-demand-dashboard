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

# slug → {city campaign token, place_id}. place_id set → isolate to that clinic's asset (multi-clinic city).
# place_id None → single-clinic city, so all T1_<tok> location-asset impressions == the clinic.
CLINICS = {
    "bharathi": {"tok": "Coimbatore", "place": None},
    "vaishali": {"tok": "Jaipur",     "place": None},
    "hubli":    {"tok": "Hubballi",   "place": None},
    "kharghar": {"tok": "Navi",       "place": "ChIJW695UsnD5zsR7wpwM4C-F9s"},
    "kharadi":  {"tok": "Pune",       "place": "ChIJew8KaAvBwjsRi0Au_Uf2p1o"},
}

def main():
    c = _creds(); token = _token(c)
    start = datetime.date.fromisoformat(WEEKS[-1])
    end = datetime.date.fromisoformat(WEEKS[0]) + datetime.timedelta(days=6)
    ymd = lambda d: d.strftime("%Y-%m-%d")

    # place_id → set of asset ids (for the multi-clinic isolations)
    arows = gaql(token, c, "SELECT asset.id, asset.location_asset.place_id FROM asset WHERE asset.type = LOCATION")
    place2ids = {}
    for r in arows:
        p = (r["asset"].get("locationAsset") or {}).get("placeId")
        if p: place2ids.setdefault(p, set()).add(r["asset"]["id"])

    rows = gaql(token, c, f"""
      SELECT campaign.name, segments.week,
        segments.asset_interaction_target.asset, segments.asset_interaction_target.interaction_on_this_asset,
        metrics.impressions, metrics.clicks
      FROM campaign
      WHERE campaign.advertising_channel_type = SEARCH AND campaign.status = ENABLED
        AND segments.date BETWEEN '{ymd(start)}' AND '{ymd(end)}'""")

    def Z(): return {m: [0]*NW for m in ('impr','clicks')}
    ctr = lambda dd: [round(dd['clicks'][i]/dd['impr'][i]*100,1) if dd['impr'][i] else None for i in range(NW)]

    for slug, cfg in CLINICS.items():
        tok = cfg["tok"]; asset_ids = place2ids.get(cfg["place"]) if cfg["place"] else None
        if cfg["place"] and not asset_ids:
            print(f"[{slug}] WARN no asset for place {cfg['place']} — skipping"); continue
        bycat = {ct: Z() for ct in CATS}; tot = Z()
        pref = (f"T1_{tok}", f"T2_{tok}")
        for r in rows:
            name = r["campaign"]["name"]
            if not name.startswith(pref): continue
            seg = r["segments"]; ait = seg.get("assetInteractionTarget") or {}
            aid = (ait.get("asset") or "").split("/")[-1]
            if not aid: continue                                   # location-asset rows only
            if asset_ids is not None and aid not in asset_ids: continue   # isolate to this clinic's asset
            wk = seg.get("week")
            if wk not in widx: continue
            i = widx[wk]; ct = cat_of(name); m = r.get("metrics", {})
            clk = int(m.get("clicks",0) or 0); imp = int(m.get("impressions",0) or 0)
            bycat[ct]['clicks'][i] += clk; tot['clicks'][i] += clk
            if not ait.get("interactionOnThisAsset", False):
                bycat[ct]['impr'][i] += imp; tot['impr'][i] += imp
        out = {"_meta": {"weeks": WEEKS, "city_token": tok, "shared": False, "place_id": cfg["place"],
                "source": "LIVE Google Ads · location-asset performance (T1_/T2_%s campaigns)" % tok,
                "note": ("Single-clinic city — city paid reach == this clinic's location-asset reach." if not cfg["place"]
                         else "Per-clinic: isolated to this clinic's location asset (place_id %s) within the multi-clinic city." % cfg["place"])},
            "total": {**tot, "ctr": ctr(tot)},
            "by_cat": {ct: {**bycat[ct], "ctr": ctr(bycat[ct])} for ct in CATS}}
        json.dump(out, open(os.path.join(ROOT, f"data_mh_{slug}_google_geo.json"), "w"), separators=(",", ":"))
        tag = "isolated" if cfg["place"] else "single-city"
        print(f"[{slug}] T1_{tok} ({tag}): impr wk1 {tot['impr'][1]} clk {tot['clicks'][1]} | "
              + " ".join(f"{ct} {bycat[ct]['impr'][1]}i" for ct in CATS if bycat[ct]['impr'][1]))

if __name__ == "__main__":
    main()
