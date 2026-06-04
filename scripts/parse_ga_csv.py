#!/usr/bin/env python3
"""Parse the weekly Google Ads campaign dashboard CSV into city-level health JSON for the
diagnostic's Google Ads drill. Keyed by city; carries the local SH (Exact) campaign's
impression share, rank-lost vs budget-lost, Quality Score + ad-relevance/LP drag, CPC, Util
and the team's Suggestion — current (W0), prior (W1) for direction, and the 12-week-avg Loc%.

The column layout matches what a campaign-level Google Ads live pull (GAQL) would produce, so
this same transform can later be fed by a live pull instead of the CSV export.

Usage:  python3 scripts/parse_ga_csv.py <weekly_dashboard.csv>  ->  writes data_ga_city.json
"""
import csv, re, json, sys

def pct(s):
    s=(s or '').strip()
    if not s or s=='—': return None
    m=re.search(r'(-?\d+(?:\.\d+)?)', s.replace('%',''))
    return round(float(m.group(1))/100,4) if m else None
def money(s):
    s=(s or '').strip()
    if not s or s=='—': return None
    m=re.search(r'(-?\d+(?:\.\d+)?)', s.replace('₹','').replace(',',''))
    return float(m.group(1)) if m else None
def num(s):
    s=(s or '').strip()
    if not s or s=='—': return None
    m=re.search(r'(-?\d+(?:\.\d+)?)', s)
    return float(m.group(1)) if m else None

def main(path):
    rows=list(csv.reader(open(path)))
    hdr=[h.strip() for h in rows[0]]
    def col(name):
        return hdr.index(name) if name in hdr else -1
    C={n:col(n) for n in ['IS (W0)','IS (W1)','Budget Lost (W0)','Budget Lost (W1)',
        'Rank Lost (W0)','Rank Lost (W1)','Ad Rel. Drag (W0)','Ad Rel. Drag (W1)',
        'LP Drag (W0)','LP Drag (W1)','Avg QS (W0)','Avg QS (W1)','CPC (W0)','CPC (W1)',
        'Util','Suggestion (Claude)','Spend Last Wk (₹)']}
    out={}
    for r in rows[1:]:
        if not r or len(r)<5: continue
        name=r[0].strip()
        # local Sexual-Health Exact campaign per city (the primary SH demand driver)
        m=re.match(r'T[12]_([A-Za-z]+(?:_[A-Za-z]+)*)_SH_Exact_Local$', name)
        if not m: continue
        city=m.group(1).replace('_',' ')
        g=lambda n: r[C[n]] if C[n]>=0 and C[n]<len(r) else ''
        out[city]={
            'is':pct(g('IS (W0)')),           'is_prev':pct(g('IS (W1)')),
            'rank_lost':pct(g('Rank Lost (W0)')), 'rank_lost_prev':pct(g('Rank Lost (W1)')),
            'budget_lost':pct(g('Budget Lost (W0)')), 'budget_lost_prev':pct(g('Budget Lost (W1)')),
            'ad_rel_drag':pct(g('Ad Rel. Drag (W0)')), 'ad_rel_drag_prev':pct(g('Ad Rel. Drag (W1)')),
            'lp_drag':pct(g('LP Drag (W0)')), 'lp_drag_prev':pct(g('LP Drag (W1)')),
            'qs':num(g('Avg QS (W0)')),       'qs_prev':num(g('Avg QS (W1)')),
            'cpc':money(g('CPC (W0)')),       'cpc_prev':money(g('CPC (W1)')),
            'util':pct(g('Util')),
            'spend_wk':money(g('Spend Last Wk (₹)')),
            'suggestion':(g('Suggestion (Claude)') or '').strip(),
            'campaign':name,
        }
    res={'_meta':{'source':'weekly Google Ads campaign dashboard CSV (SH Exact Local per city)',
                  'fields':'is/rank_lost/budget_lost/ad_rel_drag/lp_drag = impression-share %; qs=Quality Score; cpc=₹; util=budget utilization %; _prev = prior week (W1) for direction',
                  'account':'3190189170'}}
    for k in sorted(out): res[k]=out[k]
    json.dump(res, open('data_ga_city.json','w'), separators=(',',':'))
    print('cities:', len(out))

if __name__=='__main__':
    main(sys.argv[1] if len(sys.argv)>1 else '/tmp/ga_weekly.csv')
