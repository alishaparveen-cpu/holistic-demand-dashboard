#!/usr/bin/env python3
"""Competition × Google-Ads ACTION PLAN workbook.
Combines the paid funnel (IS / Loc→Lead / Lead→Book / CPL...) with the local-map-pack competition
(review gap, top rival, who beats us) to produce a scale / fix-profile / fix-booking / cut call per
city and per clinic — and flags contradictions (e.g. Google says 'scale' but the review gap is so big
that paid spend just leaks to a better-reviewed rival).

Sheets:  ① Action Highlights  ·  ② SH cities ③ STI cities ④ MH cities  ·  ⑤ SH clinics ⑥ STI clinics ⑦ MH clinics
"""
import os, json, statistics as st
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUBE = json.load(open(os.path.join(ROOT, 'data_competition.json')))
CATLBL = {'SH': 'Sexual Health', 'STI': 'STI', 'MH': 'Mental Health'}

# benchmarks
IS_T, LOC2LD_T, LOC2LD_HARD, LD2BK_T = 0.70, 0.30, 0.20, 0.65

WHITE = Font(color='FFFFFF', bold=True)
BOLD = Font(bold=True)
HDR = PatternFill('solid', fgColor='2C6CAE')
SUB = PatternFill('solid', fgColor='EEF2F8')
RED = PatternFill('solid', fgColor='F8C9C4')
AMB = PatternFill('solid', fgColor='FBE7C2')
GRN = PatternFill('solid', fgColor='CDE9D3')
GREY = PatternFill('solid', fgColor='E4E8EF')
BLU = PatternFill('solid', fgColor='D6E4F5')
thin = Side(style='thin', color='D5DBE5')
BORD = Border(left=thin, right=thin, top=thin, bottom=thin)
CEN = Alignment(horizontal='center', vertical='center', wrap_text=True)
LFT = Alignment(horizontal='left', vertical='center', wrap_text=True)

ACTFILL = {'SCALE': GRN, 'SCALE + FIX PROFILE': AMB, 'FIX PROFILE': AMB, 'FIX BOOKING': PatternFill('solid', fgColor='F6D9B8'),
           'CUT': RED, 'HOLD — efficient': GREY, 'REVIEW-ONLY (no paid spend)': BLU, 'SCALE ⚠ close reviews first': AMB}


def city_stat(cat, city):
    C = CUBE[cat]
    cc = C['cities'][city]
    keys = cc['clinics']
    revs = [C['clinics'][k]['our_reviews'] for k in keys]
    med = int(st.median(revs)) if revs else 0
    beaten = sum(1 for k in keys if any(t.startswith('beaten:') for t in C['clinics'][k]['tags']))
    tr = cc['top_rivals'][0] if cc['top_rivals'] else {}
    f = cc.get('funnel') or {}
    return dict(city=city, n=len(keys), med=med, beaten=beaten, winrate=cc.get('winrate', 0),
                rival=tr.get('name', ''), rtype=tr.get('pathy', ''), rrev=tr.get('reviews', 0), f=f)


def decide(s):
    """Return (action, why, insight)."""
    f = s['f']
    gapx = (s['rrev'] / s['med']) if s['med'] else (99 if s['rrev'] else 1)   # rival reviews ÷ our median
    big_gap = gapx >= 3
    if not f or not f.get('spend'):
        why = f"No paid spend. {s['beaten']}/{s['n']} clinics out-reviewed (top rival {s['rival']} {s['rrev']} vs our median {s['med']})."
        ins = "Organic/GMB market — build reviews & GMB before/instead of paid." if s['beaten'] else "Holding on reviews organically."
        return 'REVIEW-ONLY (no paid spend)', why, ins
    IS, l2l, l2b = f.get('IS', 0), f.get('loc2ld', 0), f.get('ld2bk', 0)
    room = IS < IS_T
    profile = l2l < LOC2LD_HARD
    profile_soft = l2l < LOC2LD_T
    booking = l2b < LD2BK_T
    why = f"IS {IS:.0%} · Loc→Lead {l2l:.0%} · Lead→Book {l2b:.0%} · CPL ₹{f.get('cpl',0)}"
    ins = ''
    if booking and not profile_soft:
        act = 'FIX BOOKING'
        ins = f"Leads arrive but stall at booking ({l2b:.0%} vs {LD2BK_T:.0%} bench) — ops: calling, availability, follow-up."
    elif profile and room:
        act = 'SCALE + FIX PROFILE'
        ins = f"Room to scale (IS {IS:.0%}) but map clicks don't convert ({l2l:.0%}); rival {s['rtype']} {s['rrev']} vs our {s['med']} reviews wins the listing. Scale + build reviews."
    elif profile or profile_soft:
        act = 'FIX PROFILE'
        ins = f"Map clicks leak — listing loses to {s['rtype']} rival ({s['rrev']} vs {s['med']} reviews). Build reviews / GMB, don't just raise budget."
    elif room and big_gap:
        act = 'SCALE ⚠ close reviews first'
        ins = f"⚠ Google shows room (IS {IS:.0%}) BUT rival out-reviews us {gapx:.0f}× ({s['rrev']} vs {s['med']}). Scaling paid spend leaks to the better-reviewed rival — fix reviews alongside."
    elif room:
        act = 'SCALE'
        ins = f"Healthy funnel + room (IS {IS:.0%}). Raise budget/bid to capture more of the {f.get('mkt',0):,}/wk market."
    else:
        act = 'HOLD — efficient'
        ins = f"Capturing most of the market (IS {IS:.0%}) with a healthy funnel. Hold; defend reviews."
    # contradiction overlay even when action isn't scale
    if 'SCALE' in act and big_gap and 'close reviews' not in act and 'PROFILE' not in act:
        ins += f"  ⚠ Note: rival out-reviews us {gapx:.0f}× — pair the scale with a review push."
    return act, why, ins


def hdr_row(ws, row, cols, widths):
    for i, (c, w) in enumerate(zip(cols, widths), 1):
        cell = ws.cell(row, i, c); cell.fill = HDR; cell.font = WHITE; cell.alignment = CEN; cell.border = BORD
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w


def flag(cell, val, bad, warn, invert=False):
    """Colour a metric cell red/amber against a benchmark (invert=True → lower is worse)."""
    if val is None: return
    below = val < bad
    warnb = val < warn
    if invert:  # e.g. cost, gap — higher is worse; here handled by caller instead
        return
    if below: cell.fill = RED
    elif warnb: cell.fill = AMB


def build():
    wb = openpyxl.Workbook()
    # ── Sheet ① Highlights ───────────────────────────────────────────────
    ws = wb.active; ws.title = '① Action Highlights'
    ws.merge_cells('A1:H1')
    t = ws.cell(1, 1, 'ACTION HIGHLIGHTS — where to Scale / Fix profile / Fix booking / Cut, and why (competition × Google Ads)')
    t.font = Font(bold=True, size=13, color='1A2230'); t.alignment = LFT
    ws.row_dimensions[1].height = 22
    hdr_row(ws, 2, ['Category', 'City', 'Clinics', 'ACTION', 'Why (funnel)', 'Insight / contradiction', 'Top rival (reviews)', 'Our median rev'],
            [14, 16, 8, 20, 26, 60, 26, 12])
    r = 3
    prio = {'FIX PROFILE': 0, 'SCALE + FIX PROFILE': 1, 'SCALE ⚠ close reviews first': 2, 'FIX BOOKING': 3,
            'CUT': 4, 'SCALE': 5, 'HOLD — efficient': 6, 'REVIEW-ONLY (no paid spend)': 7}
    highlights = []
    for cat in CUBE['_meta']['cats']:
        for city in CUBE[cat]['cities']:
            s = city_stat(cat, city)
            act, why, ins = decide(s)
            highlights.append((cat, s, act, why, ins))
    # only cities with spend OR materially beaten go to highlights; sort by priority then clinics
    hi = [h for h in highlights if (h[1]['f'].get('spend') or h[1]['beaten'])]
    hi.sort(key=lambda h: (prio.get(h[2], 9), -h[1]['n']))
    for cat, s, act, why, ins in hi:
        ws.cell(r, 1, CATLBL[cat]).border = BORD
        ws.cell(r, 2, s['city']).border = BORD
        ws.cell(r, 3, s['n']).border = BORD; ws.cell(r, 3).alignment = CEN
        a = ws.cell(r, 4, act); a.fill = ACTFILL.get(act, GREY); a.font = BOLD; a.alignment = CEN; a.border = BORD
        ws.cell(r, 5, why).border = BORD; ws.cell(r, 5).alignment = LFT
        ws.cell(r, 6, ins).border = BORD; ws.cell(r, 6).alignment = LFT
        ws.cell(r, 7, f"{s['rival']} ({s['rrev']})").border = BORD; ws.cell(r, 7).alignment = LFT
        ws.cell(r, 8, s['med']).border = BORD; ws.cell(r, 8).alignment = CEN
        ws.row_dimensions[r].height = 42
        r += 1
    ws.freeze_panes = 'A3'

    # ── Sheets ②③④ city-level per category ──────────────────────────────
    ccols = ['City', '#Clinics', 'Market/wk', 'IS', 'Spend/wk', 'CPL', 'Loc %', 'Loc→Lead', 'Lead→Book', 'Book→Done',
             'Our med rev', 'Top rival', 'Rival type', 'Rival rev', 'Gap ×', '#Beaten', 'ACTION', 'Insight / contradiction']
    cwid = [15, 8, 10, 7, 10, 8, 7, 9, 9, 9, 10, 22, 14, 9, 7, 8, 20, 55]
    for cat, sh in zip(CUBE['_meta']['cats'], ['② SH — cities', '③ STI — cities', '④ MH — cities']):
        ws = wb.create_sheet(sh)
        ws.merge_cells('A1:R1')
        t = ws.cell(1, 1, f'{CATLBL[cat]} — city action plan (Google Ads funnel × competition)'); t.font = Font(bold=True, size=12); t.alignment = LFT
        hdr_row(ws, 2, ccols, cwid)
        rows = sorted((city_stat(cat, c) for c in CUBE[cat]['cities']), key=lambda s: -(s['f'].get('spend') or 0))
        r = 3
        for s in rows:
            f = s['f']; act, why, ins = decide(s)
            gapx = (s['rrev'] / s['med']) if s['med'] else (s['rrev'] and 99 or 0)
            vals = [s['city'], s['n'], f.get('mkt'), f.get('IS'), f.get('spend'), f.get('cpl'), f.get('locpct'),
                    f.get('loc2ld'), f.get('ld2bk'), f.get('bk2dn'), s['med'], s['rival'], s['rtype'], s['rrev'],
                    round(gapx, 1) if gapx else '', s['beaten'], act, ins]
            for i, v in enumerate(vals, 1):
                cell = ws.cell(r, i, v); cell.border = BORD
                cell.alignment = LFT if i in (1, 12, 13, 18) else CEN
            # percentage formats
            for col in (4, 7, 8, 9, 10):
                if ws.cell(r, col).value is not None: ws.cell(r, col).number_format = '0%'
            for col in (3, 5, 6):
                if ws.cell(r, col).value is not None: ws.cell(r, col).number_format = '#,##0'
            # benchmark colours
            if f.get('IS') is not None and f['IS'] < IS_T: ws.cell(r, 4).fill = AMB if f['IS'] >= 0.5 else RED
            if f.get('loc2ld') is not None: ws.cell(r, 8).fill = RED if f['loc2ld'] < LOC2LD_HARD else (AMB if f['loc2ld'] < LOC2LD_T else GRN)
            if f.get('ld2bk') is not None and f['ld2bk'] < LD2BK_T: ws.cell(r, 9).fill = RED
            if gapx and gapx >= 3: ws.cell(r, 15).fill = RED
            elif gapx and gapx >= 1.5: ws.cell(r, 15).fill = AMB
            a = ws.cell(r, 17); a.fill = ACTFILL.get(act, GREY); a.font = BOLD
            ws.row_dimensions[r].height = 40
            r += 1
        ws.freeze_panes = 'A3'

    # ── Sheets ⑤⑥⑦ clinic-level per category ────────────────────────────
    kcols = ['City', 'Clinic', 'Our rev', 'Top rival', 'Rival type', 'Rival rev', 'Gap (rival−ours)', 'Ratio',
             'Dist km', 'GMB views/wk', 'Verdict', 'Clinic action']
    kwid = [14, 20, 9, 24, 15, 9, 14, 8, 8, 12, 34, 30]
    for cat, sh in zip(CUBE['_meta']['cats'], ['⑤ SH — clinics', '⑥ STI — clinics', '⑦ MH — clinics']):
        ws = wb.create_sheet(sh)
        ws.merge_cells('A1:L1')
        t = ws.cell(1, 1, f'{CATLBL[cat]} — clinic action plan (per Allo clinic vs its #1 local rival)'); t.font = Font(bold=True, size=12); t.alignment = LFT
        hdr_row(ws, 2, kcols, kwid)
        cl = CUBE[cat]['clinics']
        rows = sorted(cl.values(), key=lambda v: (v['city'], v['loc']))
        r = 3
        for v in rows:
            tr = v['competitors'][0]
            gap = v['our_reviews'] - tr['reviews']
            ratio = (v['our_reviews'] / tr['reviews']) if tr['reviews'] else None
            gmb = v.get('gmb') or {}
            act = ('Hold + keep reviews' if v['vkind'] == 'win' else
                   'Fix GMB rank/bid (we have reviews)' if v['vkind'] == 'outrank' else
                   f"Build reviews (need +{-gap} to match)")
            vals = [v['city'], v['loc'], v['our_reviews'], tr['name'], tr['pathy'], tr['reviews'], gap,
                    round(ratio, 2) if ratio is not None else '', tr.get('km') if tr.get('km') is not None else '',
                    gmb.get('searches', ''), v['verdict'], act]
            for i, x in enumerate(vals, 1):
                cell = ws.cell(r, i, x); cell.border = BORD
                cell.alignment = LFT if i in (1, 2, 4, 5, 11, 12) else CEN
            ws.cell(r, 7).fill = GRN if gap >= 0 else (RED if gap < -300 else AMB)
            if ratio is not None: ws.cell(r, 8).fill = GRN if ratio >= 1 else (AMB if ratio >= 0.5 else RED)
            if gmb.get('searches'): ws.cell(r, 10).number_format = '#,##0'
            r += 1
        ws.freeze_panes = 'A3'

    out = os.path.join(ROOT, 'Competition_Action_Plan.xlsx')
    wb.save(out)
    print('wrote', out, '·', len(hi), 'highlight rows ·', len(CUBE['_meta']['cats']), 'categories')


if __name__ == '__main__':
    build()
