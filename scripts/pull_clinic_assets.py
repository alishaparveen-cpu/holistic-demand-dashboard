#!/usr/bin/env python3
"""Per-CLINIC Google paid location-asset impressions/clicks, by category and
offline/online, via segments.asset_interaction_target.asset. Matches each clinic's
GBP location asset (data_clinic_asset_ids.json) and aggregates campaign metrics
served on that asset. Writes data_clinic_reach.json {slug:{impr,clicks,by_cat,by_seg}}.
"""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(__file__))
import pull_ga_city_paid as G
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKS, widx, NW = G.WEEKS, G.widx, G.NW; CATS = ["STI","SH","MH","Other"]
asset_key = {aid: key for key, aid in json.load(open(os.path.join(ROOT,"data_clinic_asset_ids.json"))).items()}
cfg = json.load(open(os.path.join(ROOT,"data_all_clinics_cfg.json")))
key2slug = {(c["city"]+"|"+c["loc"]): slug for slug, c in cfg.items()}
def Z(): return [0]*NW
def blank(): return {"impr":Z(),"clicks":Z(),
    "by_cat":{ct:{"impr":Z(),"clicks":Z()} for ct in CATS},
    "by_seg":{sg:{"impr":Z(),"clicks":Z(),"by_cat":{ct:{"impr":Z(),"clicks":Z()} for ct in CATS}} for sg in ("offline","online")}}

def main():
    c = G._creds(); tok = G._token(c)
    end = datetime.date.fromisoformat(WEEKS[0]) + datetime.timedelta(days=6)
    start = datetime.date.fromisoformat(WEEKS[-1])
    rows = G.gaql(tok, c, """SELECT campaign.name, segments.week,
        segments.asset_interaction_target.asset, segments.asset_interaction_target.interaction_on_this_asset,
        metrics.impressions, metrics.clicks FROM campaign
      WHERE campaign.advertising_channel_type='SEARCH' AND campaign.status='ENABLED'
        AND segments.date BETWEEN '%s' AND '%s'""" % (start.isoformat(), end.isoformat()))
    acc = {}
    for r in rows:
        seg = r.get("segments", {}); ait = seg.get("assetInteractionTarget") or {}
        aid = (ait.get("asset") or "").split("/")[-1]
        if aid not in asset_key: continue
        slug = key2slug.get(asset_key[aid])
        if not slug: continue
        wk = seg.get("week")
        if wk not in widx: continue
        i = widx[wk]; nm = r["campaign"]["name"]
        # own-city campaigns only (match the MH funnel): exclude neighbouring-city spillover
        # (e.g. T1_Mumbai serving a Navi Mumbai listing) and brand/national/online (city_of=None).
        if G.city_of(nm) != cfg[slug]["city"]: continue
        ct = G.cat_of(nm); sg = G.seg_of(nm)
        m = r.get("metrics", {}); clk = int(m.get("clicks",0) or 0); imp = int(m.get("impressions",0) or 0)
        on_asset = ait.get("interactionOnThisAsset", False)
        a = acc.setdefault(slug, blank())
        a["clicks"][i] += clk; a["by_cat"][ct]["clicks"][i] += clk
        a["by_seg"][sg]["clicks"][i] += clk; a["by_seg"][sg]["by_cat"][ct]["clicks"][i] += clk
        if not on_asset:   # impressions counted once (asset-served, not interaction rows)
            a["impr"][i] += imp; a["by_cat"][ct]["impr"][i] += imp
            a["by_seg"][sg]["impr"][i] += imp; a["by_seg"][sg]["by_cat"][ct]["impr"][i] += imp
    json.dump(acc, open(os.path.join(ROOT,"data_clinic_reach.json"),"w"), separators=(",",":"))
    print("clinic-level reach for %d clinics" % len(acc))
    for slug in list(acc)[:5]:
        print("  %-22s impr=%d clicks=%d" % (cfg[slug]["disp"], sum(acc[slug]["impr"]), sum(acc[slug]["clicks"])))

if __name__ == "__main__": main()
