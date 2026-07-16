#!/usr/bin/env python3
"""Build data_bookings_funnel.json — REAL per-episode pivot cube (unique patient-intents).

Runs fetch_booking_episodes_rich.sql and emits, per clinic, a FLAT list of cells carrying every
dimension the pivot funnel needs, so the UI can nest/filter by any of them:
  pt  patient-type : new / relapse (returning, done before) / reattempt (returning, never done)
  la  lead age     : fresh / wk1 / wk2_4 / mo1_3 / mo3   (lead → first SC)
  rg  return gap   : same buckets (prev visit → this one); 'na' for new
  rt  retry        : 0 / 1  (first attempt failed & was retried within 14d — a New that needed a retry)
  ch  channel      : GMB / Google Ads / Practo / Meta / Organic / Walk-in / Other  (taxonomy)
  md  medium       : call / web / whatsapp / book / walkin  (from lead origin/user_flow)
  w   weekly count : [12] newest-first
Plus _callcat: AI-audit call-category mix (STI/SH/MH/Other) for the provisional category split.
Run: AWS_PROFILE=redshift-data python3 scripts/build_bookings_funnel.py
"""
import os, sys, json, subprocess
from collections import defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, 'scripts', 'redshift_query.py')
WEEKS = ['2026-07-06', '2026-06-29', '2026-06-22', '2026-06-15', '2026-06-08', '2026-06-01', '2026-05-25',
         '2026-05-18', '2026-05-11', '2026-05-04', '2026-04-27', '2026-04-20', '2026-04-13',
         '2026-04-06', '2026-03-30', '2026-03-23', '2026-03-16', '2026-03-09', '2026-03-02',
         '2026-02-23', '2026-02-16', '2026-02-09', '2026-02-02', '2026-01-26', '2026-01-19',
         '2026-01-12']   # 26 weeks ending at the latest complete week (6–12 Jul)
WI = {w: i for i, w in enumerate(WEEKS)}; N = len(WEEKS)
CH = {'Google Maps (GMB)': 'GMB', 'Google Ads': 'Google Ads', 'Practo': 'Practo', 'Meta': 'Meta',
      'Organic': 'Organic', 'Walk-in': 'Walk-in'}
CATMAP = {'STI': 'STI', 'SEXUAL_HEALTH_GENERAL': 'SH', 'MENTAL_HEALTH': 'MH', 'OTHER': 'Other', 'NOT_MENTIONED': 'Other'}


def callcat(clf, cl):
    bc = (clf.get(cl) or {}).get('by_cat')
    if not bc:
        return None
    agg = {'STI': 0, 'SH': 0, 'MH': 0, 'Other': 0}
    for k, arr in bc.items():
        agg[CATMAP.get(k, 'Other')] += sum(x or 0 for x in arr)
    tot = sum(agg.values())
    return {k: round(agg[k] / tot, 4) for k in agg} if tot > 0 else None


def main():
    sql = open(os.path.join(ROOT, 'scripts', 'fetch_booking_episodes_rich.sql')).read()
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit('query failed: ' + p.stderr[-500:])
    try:
        clf = json.load(open(os.path.join(ROOT, 'data_clinic_lead_funnel.json')))
    except Exception:
        clf = {}
    # clinic -> cellkey(pt,la,ch,md,number) -> [N]   (weekly model: 1 booking / patient-week; number from utm_medium on calls)
    acc = defaultdict(lambda: defaultdict(lambda: [[0] * N, [0] * N]))   # [bookings, done] per cell
    for line in p.stdout.splitlines():
        c = line.split('\t')
        if len(c) < 15:
            continue
        city, clinic, wk, pt, la, ch, md, num, cmp, cat, diag, br, dr, n, dn = c
        if wk not in WI:
            continue
        key = f'{city}|{clinic}'
        chs = CH.get(ch, 'Other')
        md2 = md if chs != 'Other' else 'other'   # untaxonomy channels are flat
        cell = acc[key][(pt, la, chs, md2, num, cmp, cat, diag, br, dr)]
        cell[0][WI[wk]] += int(n)
        cell[1][WI[wk]] += int(dn or 0)
    out = {'_meta': {'weeks': WEEKS, 'basis': 'unique patient-intents (episodes) · REAL per-booking pull',
                     'source': 'fetch_booking_episodes_rich.sql — reschedule/rebook chains ≤14d collapsed; '
                               'pt=new/relapse/reattempt, la=lead-age, rg=return-gap, rt=needed-retry, real medium. '
                               'Category (STI/SH/MH/Other) still a provisional AI-audit prior on call leads (_callcat).'}}
    for key, cells in acc.items():
        arr = [{'pt': k[0], 'la': k[1], 'ch': k[2], 'md': k[3], 'num': k[4], 'cmp': k[5], 'cat': k[6], 'dg': k[7], 'br': k[8], 'dr': k[9], 'w': v[0], 'wd': v[1]} for k, v in cells.items()]
        out[key] = {'cells': arr, '_callcat': callcat(clf, key)}
    json.dump(out, open(os.path.join(ROOT, 'data_bookings_funnel.json'), 'w'), separators=(',', ':'))
    K = 'Bangalore|Indiranagar'; n8 = 8
    nclin = len([k for k in out if k != '_meta'])
    print(f'wrote data_bookings_funnel.json · {nclin} clinics')
    if K in out:
        from collections import Counter
        pt = Counter()
        for c in out[K]['cells']:
            pt[c['pt']] += sum(c['w'][:n8])
        print(f'  {K} 8wk by ptype: {dict(pt)}  total={sum(pt.values())}')
        print(f'  _callcat: {out[K]["_callcat"]}')


if __name__ == '__main__':
    main()
