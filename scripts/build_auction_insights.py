#!/usr/bin/env python3
"""Ingest Google Ads AUCTION INSIGHTS CSV exports (one per campaign) -> data_auction_insights.json.

Auction-insight competitor metrics are NOT available to our Google Ads API token (Google gates them
behind elevated access) and the UI has no per-campaign segment, so we export one CSV per campaign from
    Google Ads -> (scope to a campaign) -> Auction insights -> Download.
The CSV holds the competitor table but NOT the campaign name, so each file is mapped to a campaign by:
  1. its FILENAME if it contains a `<City>_<SH|STD|MH>` token  (preferred -- rename downloads to e.g.
     `Hyderabad_SH.csv`, `Mumbai_STD.csv`, `Jaipur_MH.csv`), else
  2. the LEGACY_MAP below (for the first batch of generically-named `Auction insights report (N).csv`).

Handles both export encodings: UTF-8 comma-CSV and UTF-16 tab-TSV.
Run:  python3 build_auction_insights.py [~/Downloads]
"""
import csv, io, json, os, re, sys, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRCDIR = os.path.expanduser(sys.argv[1]) if len(sys.argv) > 1 else os.path.expanduser('~/Downloads')

# STD (campaign vocab) == STI (competition-cube vocab); keep both.
CAT_NORM = {'SH': 'SH', 'STD': 'STI', 'STI': 'STI', 'MH': 'MH'}

# Legacy map: first batch of generic filenames -> "City_CAT". Fill in as cities are confirmed.
LEGACY_MAP = {
    'Auction insights report.csv':     'Bangalore_SH',   # confirmed (You 51.67%, milann, themenscareclinic)
    'Auction insights report (2).csv': 'Pune_SH',        # confirmed (topsexologistinpune.com)
    'Auction insights report (5).csv': 'Chennai_SH',     # confirmed (drkamarajhospital, arunmuthuvel)
    'Auction insights report (7).csv': 'Hyderabad_STD',  # confirmed (vijayadiagnostic.com = Hyderabad)
    'Auction insights report (8).csv': 'Mumbai_STD',     # confirmed (suburbandiagnostics.com = Mumbai)
    # pending user confirmation (city unclear -- national competitors):
    # 'Auction insights report (1).csv': 'Hyderabad_SH',   # ? homeocare.in, oasisindia
    # 'Auction insights report (3).csv': 'Mumbai_SH',      # ? ashakiran, drskjain, gautamayurveda
    # 'Auction insights report (4).csv': 'NaviMumbai_SH',  # ?
    # 'Auction insights report (6).csv': '?_STD',          # ? orangehealth, lalpathlabs
    # 'Auction insights report (9).csv': '?_STD',          # ? 1mg, metropolis, drhivaidsonline
}

COLS = ['is', 'overlap', 'posAbove', 'top', 'absTop', 'outrank']

def readrows(path):
    raw = open(path, 'rb').read()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff') or b'\x00' in raw[:40]:
        txt, delim = raw.decode('utf-16'), '\t'
    else:
        txt, delim = raw.decode('utf-8-sig'), ','
    return list(csv.reader(io.StringIO(txt), delimiter=delim))

def norm_pct(x):
    x = (x or '').strip()
    return None if x in ('', '--', '—', '- -') else x  # keep "< 10%" and "41.03%" verbatim as display strings

def parse_campaign(token):
    """`City_CAT` -> (city, rawcat). Accepts CamelCase / underscores; strips T1_/T2_/_Exact_Local."""
    t = re.sub(r'^[Tt]\d[_\- ]*', '', token)
    t = re.sub(r'[_\- ]*Exact[_\- ]*Local$', '', t, flags=re.I)
    m = re.match(r'(.+?)[_\- ]+(SH|STD|STI|MH)$', t, re.I)
    if not m:
        return None, None
    city = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', m.group(1)).replace('_', ' ').strip()
    return city, m.group(2).upper()

def file_token(fn):
    base = os.path.splitext(os.path.basename(fn))[0]
    if re.search(r'_(SH|STD|STI|MH)\b', base, re.I) and 'Auction insights report' not in base:
        return base
    return LEGACY_MAP.get(os.path.basename(fn))

def main():
    files = sorted(glob.glob(os.path.join(SRCDIR, '*.csv')))
    out = {}       # city -> cat(norm) -> {you, competitors:[...]}
    seen = []
    skipped = []
    for f in files:
        tok = file_token(f)
        if not tok:
            skipped.append(os.path.basename(f)); continue
        city, rawcat = parse_campaign(tok)
        if not city:
            skipped.append(os.path.basename(f) + f' (bad token {tok})'); continue
        cat = CAT_NORM.get(rawcat, rawcat)
        rows = readrows(f)
        hi = next((i for i, r in enumerate(rows) if r and 'Display URL domain' in (r[0] or '')), None)
        if hi is None:
            skipped.append(os.path.basename(f) + ' (no header)'); continue
        you, comps = None, []
        for r in rows[hi + 1:]:
            if not r or not (r[0] or '').strip():
                continue
            dom = r[0].strip()
            rec = {'domain': dom}
            for j, k in enumerate(COLS):
                rec[k] = norm_pct(r[j + 1]) if j + 1 < len(r) else None
            if dom.lower() == 'you':
                you = rec
            else:
                comps.append(rec)
        # sort competitors by impression share desc ("< 10%" and None sink to bottom)
        def is_key(rec):
            v = rec.get('is')
            try: return float(str(v).replace('%', '').replace('<', '').strip())
            except (TypeError, ValueError): return -1
        comps.sort(key=is_key, reverse=True)
        out.setdefault(city, {})[cat] = {'you': (you or {}).get('is'), 'youRow': you, 'competitors': comps}
        seen.append(f'{city}/{cat} ({len(comps)} rivals)')

    result = {
        '_meta': {'source': 'Google Ads Auction Insights (per-campaign CSV export)',
                  'metrics': ['Impression share', 'Overlap rate', 'Position above rate',
                              'Top of page rate', 'Abs. Top of page rate', 'Outranking share'],
                  'cols': COLS, 'cities': sorted(out.keys())},
        'byCity': out,
    }
    dst = os.path.join(ROOT, 'data_auction_insights.json')
    json.dump(result, open(dst, 'w'), indent=1)
    print(f'wrote {dst}')
    print(f'  ingested {len(seen)}: ' + '; '.join(seen))
    if skipped:
        print(f'  skipped {len(skipped)} (no campaign mapping): ' + '; '.join(skipped))

if __name__ == '__main__':
    main()
