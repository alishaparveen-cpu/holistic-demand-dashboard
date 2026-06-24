#!/usr/bin/env python3
"""Build data_efficiency.json for the Channel Efficiency view from the L0 marketing sheet.
Produces network (ALL) + per-channel contribution (CONTR) + direct overrides (DIRECT) for
weekly and monthly, in the shape the efficiency.html funnel view expects (oldest-first arrays).
Run: python3 scripts/build_efficiency.py   (no auth — public sheet)"""
import os, sys, csv, io, json, urllib.request, urllib.parse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
L0_ID = "1jyyFYpd7gfYyAQ3U7E56c7OA3OuQQAVgJrAGyQr90XM"
URL = f"https://docs.google.com/spreadsheets/d/{L0_ID}/gviz/tq?tqx=out:csv&sheet=L0"

def num(s):
    if s is None: return None
    c = str(s).strip().replace('%','').replace(',','').replace('₹','').replace(' ','')
    if c == '' or c == '-': return None
    try: return float(c)
    except ValueError: return None

def main():
    txt = urllib.request.urlopen(URL, timeout=60).read().decode('utf-8')
    rows = list(csv.reader(io.StringIO(txt)))
    end = [c.strip() for c in rows[1]]            # row1 = week-END labels

    # ── choose columns ──
    # weekly: cols 2..N that have lead data (>100) — newest-first in the sheet
    leads_row = rows[6]
    weekly_nf = [c for c in range(2, 14) if (num(leads_row[c]) or 0) > 100]
    weekly = list(reversed(weekly_nf))            # oldest-first
    wk_labels = [end[c] for c in weekly]
    # monthly: the two MTD/last-month rollup cols (14=latest month, 15=prev) — oldest-first
    monthly = [15, 14]
    mo_labels = [end[c] for c in monthly]

    def arr(ri, cols):
        r = rows[ri] if ri < len(rows) else []
        return [num(r[c]) if c < len(r) else None for c in cols]

    # ── network OVERALL block (row indices fixed by the L0 label layout) ──
    NET = {  # metric : row index
        'spend':3,'leads':6,'vleads':7,'vpct':8,'cpl':9,'bookings':10,'bkOn':11,'bkOff':12,
        'b2l':13,'cpb':14,'done':15,'dnOn':16,'dnOff':17,'cpd':19,
        'dnSH':20,'dnSHon':21,'dnSHoff':22,'dnSTI':23,'dnSTIon':24,'dnSTIoff':25,
        'sti':26,'stiOn':27,'stiOff':28,'b2d':29,'b2dOn':30,'b2dOff':31,
        'tpRev':32,'consultRev':33,'newRev':34,'roas':35,'rpc':36,'tpOn':37,
        'aov':39,'convOn':40,'tpOff':42,'convOff':45,
    }
    def build_all(cols):
        a = {k: arr(ri, cols) for k, ri in NET.items()}
        n = len(cols)
        a['tp'] = [ (a['tpOn'][i] or 0)+(a['tpOff'][i] or 0) if (a['tpOn'][i] is not None or a['tpOff'][i] is not None) else None for i in range(n) ]
        a['done2tp'] = [ round(a['tp'][i]/a['done'][i]*100) if a['tp'][i] and a['done'][i] else None for i in range(n) ]
        return a

    # ── per-channel sections: header row → 4 contribution rows; + direct rows ──
    # contr rows are the 4 rows after the channel header (Spend/Lead/Booking/Done Contr.)
    CH = {   # key : (contr_header_row, {direct_metric: row})
        'organic':  (47, {}),
        'gmbgoogle':(84, {'spend':89,'impr':90,'cpm':91,'clicks':92,'ctr':93,'cpc':94,'cpl':99,'cpb':104,'cpd':109,'roas':125}),
        'gmb':      (133,{'spend':138,'cpm':140,'cpc':143,'cpl':148,'cpb':153,'cpd':158,'roas':169}),
        'gsearch':  (181,{'spend':187,'cpm':189,'cpc':190,'cpl':191,'cpb':192,'cpd':193,'roas':195}),
        'practo':   (207,{'spend':213,'cpl':222,'cpb':229,'cpd':234,'roas':246}),
        'meta':     (261,{'spend':266,'cpm':270,'cpc':273,'cpl':274,'cpb':275,'cpd':276,'roas':278}),
    }
    def build_contr(cols):
        out = {}
        for k,(hdr,_) in CH.items():
            out[k] = {'spend':arr(hdr+1,cols),'lead':arr(hdr+2,cols),'book':arr(hdr+3,cols),'done':arr(hdr+4,cols)}
        return out
    def build_direct(cols):
        out = {}
        for k,(_,dm) in CH.items():
            d = {m:arr(ri,cols) for m,ri in dm.items()}
            d = {m:v for m,v in d.items() if any(x is not None for x in v)}   # drop empty
            if d: out[k] = d
        return out

    data = {
        '_meta': {'source':'L0 marketing sheet (gviz CSV)','sheet':'L0','weekly':wk_labels,'monthly':mo_labels},
        'weekly':  {'periods':wk_labels, 'ALL':build_all(weekly),  'CONTR':build_contr(weekly),  'DIRECT':build_direct(weekly)},
        'monthly': {'periods':mo_labels, 'ALL':build_all(monthly), 'CONTR':build_contr(monthly), 'DIRECT':build_direct(monthly)},
    }
    json.dump(data, open(os.path.join(ROOT,'data_efficiency.json'),'w'), separators=(',',':'))
    a = data['weekly']['ALL']
    print(f"data_efficiency.json · weekly={wk_labels} · monthly={mo_labels}")
    print(f"  latest wk: spend ₹{a['spend'][-1]:.0f} · leads {a['leads'][-1]:.0f} · bookings {a['bookings'][-1]:.0f} · done {a['done'][-1]:.0f} · roas {a['roas'][-1]:.0f}% · newRev ₹{a['newRev'][-1]}L")
    print(f"  channels: {list(data['weekly']['CONTR'].keys())}  · direct: {list(data['weekly']['DIRECT'].keys())}")

if __name__ == '__main__':
    main()
