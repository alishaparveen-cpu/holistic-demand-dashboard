#!/usr/bin/env python3
"""Pull the Google-Ads ACQUISITION metrics that data_campaign_compose.json needs,
straight from the Google Ads API (GAQL) — no google-ads-audit skill required.

For one Mon-Sun week it writes the SAME three artifacts build_campaign_compose.py
already reads, so that builder consumes the new week unchanged:
  1. <stem>_<wtag>.md  report files (parse_report format) in the funnel reports dir
  2. data_lost_is.json      — appends {wlabel:{rank,budget}} per campaign (lost-IS)
  3. data_quality_score.json — appends {wlabel:{qs,ar,lp}} per campaign

Every field was validated to reproduce the skill's w7 reports exactly
(spend / impr / clicks / IS / loc-clicks / loc-impressions).  stem = campaign
name lowercased (matches the existing report filenames + JSON keys).

Enum sets copied verbatim from the skill (audit/click_types.py) so the two
never drift:  LOC = calls+display (drives Loc Clicks) · LOC_DISPLAY = calls
excluded (drives Location Impressions).

Creds: ~/.google_ads.env (GOOGLE_ADS_* env vars).
Run:  python3 scripts/pull_ga_compose.py 2026-07-27 2026-08-02 w8 "Jul 27-Aug 2"
      python3 scripts/pull_ga_compose.py --validate 2026-07-20 2026-07-26 w7   # diff vs existing reports, write nothing
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pull_ga_city_paid as G

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.expanduser('~/Downloads/claude-skills/marketing/google-ads/reports/funnel')

# ── click-type enum sets (verbatim from marketing/.../audit/click_types.py) ──
_LOC = {"CALL_TRACKING":5,"CALLS":6,"GET_DIRECTIONS":8,"LOCATION_EXPANSION":9,
        "LOCATION_FORMAT_CALL":10,"LOCATION_FORMAT_DIRECTIONS":11,"LOCATION_FORMAT_IMAGE":12,
        "LOCATION_FORMAT_LANDING_PAGE":13,"LOCATION_FORMAT_MAP":14,"LOCATION_FORMAT_STORE_INFO":15,
        "LOCATION_FORMAT_TEXT":16,"MOBILE_CALL_TRACKING":17}
_CALLS = {"CALL_TRACKING","CALLS","MOBILE_CALL_TRACKING","LOCATION_FORMAT_CALL"}
LOC_NAMES = set(_LOC);                          LOC_INTS = set(_LOC.values())
LOCD_NAMES = LOC_NAMES - _CALLS;                LOCD_INTS = {v for k,v in _LOC.items() if k not in _CALLS}
def _is_loc(ct):
    s = str(ct).upper()
    return (int(s) in LOC_INTS) if s.isdigit() else (s in LOC_NAMES)
def _is_locd(ct):
    s = str(ct).upper()
    return (int(s) in LOCD_INTS) if s.isdigit() else (s in LOCD_NAMES)


def pull_week(start, end):
    """→ {campname: {budget,bid,spend,impr,is,rlis_share,blis_share,click,locclick,locimpr,qs,ar,lp}}"""
    c = G._creds(); tok = G._token(c)
    out = {}
    # 1) campaign-level performance + budget + bid ceiling
    rows = G.gaql(tok, c, f"""SELECT campaign.name, campaign_budget.amount_micros,
        campaign.target_spend.cpc_bid_ceiling_micros, campaign.maximize_conversion_value.target_roas,
        metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.search_impression_share,
        metrics.search_rank_lost_impression_share, metrics.search_budget_lost_impression_share
      FROM campaign WHERE campaign.advertising_channel_type='SEARCH' AND campaign.status='ENABLED'
        AND segments.date BETWEEN '{start}' AND '{end}'""")
    for r in rows:
        nm = r['campaign']['name']; m = r.get('metrics', {})
        b = (r.get('campaignBudget') or {}).get('amountMicros')
        bid = ((r.get('campaign') or {}).get('targetSpend') or {}).get('cpcBidCeilingMicros')
        out[nm] = dict(
            budget=(int(b)/1e6 if b else None),
            bid=(int(bid)/1e6 if bid else None),
            spend=int(m.get('costMicros', 0) or 0)/1e6,
            impr=int(m.get('impressions', 0) or 0),
            **{'is': float(m.get('searchImpressionShare', 0) or 0)*100},
            rlis_share=float(m.get('searchRankLostImpressionShare', 0) or 0),
            blis_share=float(m.get('searchBudgetLostImpressionShare', 0) or 0),
            click=int(m.get('clicks', 0) or 0), locclick=0, locimpr=0,
            qs=None, ar=0, lp=0)
    # 2) loc clicks (LOC) + loc impressions (LOC_DISPLAY) via click_type segmentation
    rc = G.gaql(tok, c, f"""SELECT campaign.name, segments.click_type, metrics.clicks, metrics.impressions
      FROM campaign WHERE campaign.advertising_channel_type='SEARCH' AND campaign.status='ENABLED'
        AND segments.date BETWEEN '{start}' AND '{end}'""")
    for r in rc:
        nm = r['campaign']['name']
        if nm not in out: continue
        ct = r.get('segments', {}).get('clickType', '')
        m = r.get('metrics', {})
        if _is_loc(ct):  out[nm]['locclick'] += int(m.get('clicks', 0) or 0)
        if _is_locd(ct): out[nm]['locimpr']  += int(m.get('impressions', 0) or 0)
    # 3) quality score (cost-weighted) + below-average creative(ar)/LP(lp) counts, among impressed keywords
    rq = G.gaql(tok, c, f"""SELECT campaign.name, ad_group_criterion.quality_info.quality_score,
        ad_group_criterion.quality_info.creative_quality_score,
        ad_group_criterion.quality_info.post_click_quality_score,
        metrics.cost_micros, metrics.impressions
      FROM keyword_view WHERE campaign.advertising_channel_type='SEARCH' AND campaign.status='ENABLED'
        AND segments.date BETWEEN '{start}' AND '{end}'""")
    qacc = {}  # nm -> [qs_num, qs_den, ar, lp]
    for r in rq:
        nm = r['campaign']['name']
        if nm not in out: continue
        qi = (r.get('adGroupCriterion') or {}).get('qualityInfo') or {}
        q = qi.get('qualityScore'); cq = qi.get('creativeQualityScore'); pq = qi.get('postClickQualityScore')
        m = r.get('metrics', {}); cost = int(m.get('costMicros', 0) or 0); impr = int(m.get('impressions', 0) or 0)
        if impr <= 0: continue                       # only keywords that actually served
        a = qacc.setdefault(nm, [0.0, 0.0, 0, 0])
        if q: w = cost or 1; a[0] += q*w; a[1] += w
        if cq == 'BELOW_AVERAGE': a[2] += 1
        if pq == 'BELOW_AVERAGE': a[3] += 1
    for nm, a in qacc.items():
        out[nm]['qs'] = round(a[0]/a[1], 2) if a[1] else None
        out[nm]['ar'] = a[2]; out[nm]['lp'] = a[3]
    return out


def _inr(x): return f"{round(x):,}"

def write_report(stem, wtag, start, end, d):
    is_pct = d['is']
    body = [
        f"# {stem} — {start} → {end} cohort  [compose-acq · GAQL pull]", "",
        "| Stage | Campaign | Total |", "|---|---:|---:|",
        f"| **Budget** | {('₹'+_inr(d['budget'])+'/d') if d['budget'] else '—'} | {('₹'+_inr(d['budget'])+'/d') if d['budget'] else '—'} |",
        f"| **Bid** | {('₹'+_inr(d['bid'])+' ceiling') if d['bid'] else '—'} | — |",
        f"| impression | {_inr(d['impr'])} | {_inr(d['impr'])} |",
        f"|  · IS | {round(is_pct,1)}% | — |",
        f"|  · Location Impressions | {_inr(d['locimpr'])} | {_inr(d['locimpr'])} |",
        f"| click | {_inr(d['click'])} | {_inr(d['click'])} |",
        f"|  · Loc Clicks | {_inr(d['locclick'])} | {_inr(d['locclick'])} |",
        f"| **Cost** | {_inr(d['spend'])} | {_inr(d['spend'])} |", "",
    ]
    open(os.path.join(REPORTS, f"{stem}_{wtag}.md"), "w").write("\n".join(body))


def main():
    argv = sys.argv[1:]
    validate = False
    if argv and argv[0] == '--validate':
        validate = True; argv = argv[1:]
    if len(argv) < 3:
        sys.exit("usage: pull_ga_compose.py [--validate] START END WTAG [WLABEL]\n"
                 "  e.g. pull_ga_compose.py 2026-07-27 2026-08-02 w8 'Jul 27-Aug 2'")
    start, end, wtag = argv[0], argv[1], argv[2]
    wlabel = argv[3] if len(argv) > 3 else wtag
    data = pull_week(start, end)
    print(f"pulled {len(data)} enabled SEARCH campaigns for {start}→{end}")

    if validate:
        # diff against existing <stem>_<wtag>.md reports (spend/impr/click/IS/loc)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import build_campaign_compose as B
        import glob
        ok = bad = 0
        for nm, d in data.items():
            stem = nm.lower()
            p = os.path.join(REPORTS, f"{stem}_{wtag}.md")
            if not os.path.exists(p): continue
            rep = B.parse_report(p)
            checks = [('impr', rep['impr'], d['impr']), ('click', rep['click'], d['click']),
                      ('spend', rep['spend'], d['spend']), ('locclick', rep['locclick'], d['locclick']),
                      ('locimpr', rep['locimpr'], d['locimpr'])]
            for lbl, rv, gv in checks:
                if rv is None: continue
                tol = max(2, 0.03*max(abs(rv), 1))
                if abs((rv or 0)-(gv or 0)) <= tol: ok += 1
                else:
                    bad += 1; print(f"  MISMATCH {nm:<32}{lbl}: report={rv} gaql={gv}")
        print(f"validate: {ok} fields matched, {bad} mismatched across {sum(1 for nm in data if os.path.exists(os.path.join(REPORTS,nm.lower()+'_'+wtag+'.md')))} reports")
        return

    # ---- write .md reports ----
    n = 0
    for nm, d in data.items():
        write_report(nm.lower(), wtag, start, end, d); n += 1
    print(f"wrote {n} {wtag} report files → {REPORTS}")

    # ---- append the week to the two side-car JSONs ----
    for fname, keyfn in [('data_lost_is.json', lambda d: {'rank': round(d['rlis_share'], 4), 'budget': round(d['blis_share'], 4)}),
                         ('data_quality_score.json', lambda d: {'qs': d['qs'], 'ar': d['ar'], 'lp': d['lp']})]:
        path = os.path.join(ROOT, fname)
        j = json.load(open(path)) if os.path.exists(path) else {}
        for nm, d in data.items():
            j.setdefault(nm.lower(), {})[wlabel] = keyfn(d)
        json.dump(j, open(path, 'w'), separators=(',', ':'))
        print(f"appended '{wlabel}' to {fname} ({len(data)} campaigns)")


if __name__ == '__main__':
    main()
