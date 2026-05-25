"""
Analyze pulled GMB reviews.

Outputs:
  reviews_summary.csv — per-location: avg stars (all-time, last 90d, prior 90d),
                       review velocity, response rate, low-star count, dominant theme
  reviews_by_city.csv — per-city aggregate

Prints to stdout: the core findings answering "does review experience explain
the Bangalore-cluster decline in T1 bookings?"
"""
from __future__ import annotations
import csv
import datetime as dt
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
NOW = dt.datetime.now(dt.timezone.utc)
W_RECENT = NOW - dt.timedelta(days=90)
W_PRIOR_START = NOW - dt.timedelta(days=180)

# Theme keywords for low-star (≤3) reviews
THEMES = {
    'fees_high':   re.compile(r'\b(fee|expensive|cost|charge|money|refund|price|over[- ]?charg)', re.I),
    'wait_time':   re.compile(r'\b(wait|delay|late|long\s*time|hours?)', re.I),
    'no_doctor':   re.compile(r'\b(no\s*doctor|doctor\s*not|no\s*one|unavailable|absent|wasnt\s*there)', re.I),
    'no_results':  re.compile(r'\b(no\s*result|didn\'?t\s*help|no\s*improvement|not\s*work|waste)', re.I),
    'rude_staff':  re.compile(r'\b(rude|unprofessional|bad\s*behav|attitude|disrespect)', re.I),
    'fake_clinic': re.compile(r'\b(scam|fraud|fake|cheat|loot)', re.I),
    'closed':      re.compile(r'\b(closed|shut|not\s*open|not\s*operating)', re.I),
}


def parse_dt(s):
    # 2024-12-31T...Z
    try:
        return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    except Exception:
        return None


def load_reviews():
    rows = []
    with open(HERE / 'reviews.csv') as f:
        for r in csv.DictReader(f):
            r['stars'] = int(r['stars']) if r['stars'] else None
            r['create_dt'] = parse_dt(r['create_time'])
            rows.append(r)
    return rows


def main():
    rows = load_reviews()
    print(f'{len(rows):,} reviews · {len({r["location_id"] for r in rows})} locations')

    # ===== Per-location summary =====
    by_loc = defaultdict(list)
    for r in rows:
        by_loc[r['location_id']].append(r)

    loc_meta = {}
    for lid, rs in by_loc.items():
        loc_meta[lid] = {
            'title': rs[0]['title'], 'city': rs[0]['city'] or '?',
            'store_code': rs[0]['store_code'],
        }

    summaries = []
    for lid, rs in by_loc.items():
        stars_all = [r['stars'] for r in rs if r['stars']]
        rs_recent = [r for r in rs if r['create_dt'] and r['create_dt'] >= W_RECENT]
        rs_prior = [r for r in rs if r['create_dt'] and W_PRIOR_START <= r['create_dt'] < W_RECENT]
        stars_recent = [r['stars'] for r in rs_recent if r['stars']]
        stars_prior = [r['stars'] for r in rs_prior if r['stars']]
        low_recent = [r for r in rs_recent if r['stars'] and r['stars'] <= 3 and (r['text'] or '').strip()]
        themes = Counter()
        for r in low_recent:
            for k, rx in THEMES.items():
                if rx.search(r['text'] or ''):
                    themes[k] += 1
        replies_recent = sum(1 for r in rs_recent if r['has_reply'] == 'True')
        summaries.append({
            'location_id': lid,
            'title': loc_meta[lid]['title'][:60],
            'city': loc_meta[lid]['city'],
            'n_all': len(rs),
            'avg_all': round(statistics.mean(stars_all), 2) if stars_all else None,
            'n_recent90': len(rs_recent),
            'avg_recent90': round(statistics.mean(stars_recent), 2) if stars_recent else None,
            'n_prior90': len(rs_prior),
            'avg_prior90': round(statistics.mean(stars_prior), 2) if stars_prior else None,
            'velocity_change': (len(rs_recent) - len(rs_prior)) / max(len(rs_prior), 1),
            'low_star_recent': len(low_recent),
            'response_rate_recent': round(replies_recent / max(len(rs_recent), 1), 2),
            'top_theme': themes.most_common(1)[0][0] if themes else None,
            'theme_counts': dict(themes),
        })

    # Write per-location CSV
    keys = ['location_id', 'title', 'city', 'n_all', 'avg_all',
            'n_recent90', 'avg_recent90', 'n_prior90', 'avg_prior90',
            'velocity_change', 'low_star_recent', 'response_rate_recent', 'top_theme']
    with open(HERE / 'reviews_summary.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
        w.writeheader()
        for s in summaries:
            w.writerow(s)

    # ===== Per-city =====
    by_city = defaultdict(list)
    for s in summaries:
        by_city[s['city']].append(s)

    city_keys = ['city', 'n_locations', 'reviews_recent90', 'reviews_prior90',
                 'avg_stars_recent', 'avg_stars_prior', 'avg_response_rate', 'common_themes']
    city_rows = []
    for city, ss in by_city.items():
        rec_n = sum(s['n_recent90'] for s in ss)
        pri_n = sum(s['n_prior90'] for s in ss)
        rec_stars = [s['avg_recent90'] for s in ss if s['avg_recent90'] is not None]
        pri_stars = [s['avg_prior90'] for s in ss if s['avg_prior90'] is not None]
        resp = [s['response_rate_recent'] for s in ss]
        themes_agg = Counter()
        for s in ss:
            for k, v in (s.get('theme_counts') or {}).items():
                themes_agg[k] += v
        city_rows.append({
            'city': city,
            'n_locations': len(ss),
            'reviews_recent90': rec_n,
            'reviews_prior90': pri_n,
            'avg_stars_recent': round(statistics.mean(rec_stars), 2) if rec_stars else None,
            'avg_stars_prior': round(statistics.mean(pri_stars), 2) if pri_stars else None,
            'avg_response_rate': round(statistics.mean(resp), 2) if resp else None,
            'common_themes': ' · '.join(f'{k}({v})' for k, v in themes_agg.most_common(3)),
        })
    city_rows.sort(key=lambda r: -r['reviews_recent90'])
    with open(HERE / 'reviews_by_city.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=city_keys)
        w.writeheader()
        for r in city_rows:
            w.writerow(r)

    # ===== KEY FINDINGS =====
    print('\n' + '=' * 70)
    print('PER-CITY (Tier-1 = first 8 metros by booking volume)')
    print('=' * 70)
    # GBP uses "Bengaluru" — accept both spellings
    T1 = {'Bangalore', 'Bengaluru', 'Mumbai', 'Delhi', 'Hyderabad', 'Chennai', 'Kolkata', 'Pune', 'Ahmedabad'}
    print(f'{"City":<14} {"Locs":>4} {"Rev90":>6} {"RevPri":>7} {"Δrev":>7} {"⭐Rec":>5} {"⭐Pri":>5} {"Δ⭐":>5} {"Resp%":>6}  Themes')
    for r in city_rows:
        if r['avg_stars_recent'] is None or r['avg_stars_prior'] is None:
            continue
        tier = 'T1' if r['city'] in T1 else 'T2'
        d_rev = ((r['reviews_recent90'] - r['reviews_prior90']) / max(r['reviews_prior90'], 1)) * 100
        d_star = r['avg_stars_recent'] - r['avg_stars_prior']
        print(f'{r["city"]:<14} {r["n_locations"]:>4} {r["reviews_recent90"]:>6} {r["reviews_prior90"]:>7} {d_rev:>+6.0f}% {r["avg_stars_recent"]:>5.2f} {r["avg_stars_prior"]:>5.2f} {d_star:>+5.2f} {r["avg_response_rate"]*100:>5.0f}%  [{tier}] {r["common_themes"]}')

    # ===== Per-location callouts for the failing T1 clinics =====
    # Read the booking-change data to flag declining clinics in the output
    print('\n' + '=' * 70)
    print('BANGALORE clinics (the failing cluster) — per-location review picture')
    print('=' * 70)
    blr = [s for s in summaries if s['city'] in ('Bangalore', 'Bengaluru')]
    blr.sort(key=lambda s: -s['n_recent90'])
    print(f'{"Title":<55} {"⭐All":>5} {"⭐90":>5} {"⭐pri":>5} {"N90":>4} {"Pri":>4} {"Δrev":>6} {"Resp":>5}  Theme')
    for s in blr:
        d_rev = (s['n_recent90'] - s['n_prior90']) / max(s['n_prior90'], 1) * 100
        print(f'{s["title"][:54]:<55} {(s["avg_all"] or 0):>5.2f} {(s["avg_recent90"] or 0):>5.2f} {(s["avg_prior90"] or 0):>5.2f} {s["n_recent90"]:>4} {s["n_prior90"]:>4} {d_rev:>+5.0f}% {s["response_rate_recent"]*100:>4.0f}%  {s["top_theme"] or "—"}')

    # ===== Failing T1 set: pulled from earlier dashboard analysis =====
    # Declining T1 clinics from data.json analysis (Δbookings < -10%)
    print('\n' + '=' * 70)
    print('REVIEW PICTURE: T1 with city-level booking decline vs growth')
    print('=' * 70)
    declining_cities = {'Bangalore', 'Bengaluru'}  # the cluster
    growing_t1 = {'Hyderabad', 'Pune', 'Mumbai'}  # T1 cities with +bookings
    decl = [s for s in summaries if s['city'] in declining_cities]
    grow = [s for s in summaries if s['city'] in growing_t1]
    for label, group in [('Declining T1 (Bangalore cluster)', decl),
                         ('Growing/mixed T1 (Hyderabad, Pune)', grow)]:
        if not group:
            continue
        stars_r = [s['avg_recent90'] for s in group if s['avg_recent90']]
        stars_p = [s['avg_prior90'] for s in group if s['avg_prior90']]
        velo_r = sum(s['n_recent90'] for s in group)
        velo_p = sum(s['n_prior90'] for s in group)
        resp = [s['response_rate_recent'] for s in group]
        low = sum(s['low_star_recent'] for s in group)
        print(f'\n{label}:  {len(group)} locations')
        print(f'  avg ⭐ recent  vs prior:  {statistics.mean(stars_r):.2f}  vs  {statistics.mean(stars_p):.2f}')
        print(f'  reviews recent90 vs prior90:  {velo_r}  vs  {velo_p}  (Δ {((velo_r-velo_p)/max(velo_p,1))*100:+.0f}%)')
        print(f'  response rate (recent): {statistics.mean(resp)*100:.0f}%')
        print(f'  ≤3-star reviews in last 90d: {low}')

    # ===== Direct answer =====
    print('\n' + '=' * 70)
    print('DIRECT ANSWER: does review experience explain the T1 decline?')
    print('=' * 70)
    # Build per-clinic correlation: clinics with bigger ⭐ drop should also be declining
    # Print outliers — locations where ⭐ dropped > 0.3 in recent 90 vs prior
    big_drops = [s for s in summaries
                 if s['avg_recent90'] and s['avg_prior90'] and
                 s['n_recent90'] >= 5 and s['n_prior90'] >= 5 and
                 (s['avg_prior90'] - s['avg_recent90']) > 0.3]
    big_drops.sort(key=lambda s: s['avg_prior90'] - s['avg_recent90'], reverse=True)
    print(f'\nLocations with star-rating drop > 0.3 in last 90d (n_recent≥5, n_prior≥5): {len(big_drops)}')
    for s in big_drops[:15]:
        drop = s['avg_prior90'] - s['avg_recent90']
        print(f'  {s["title"][:50]:<50} {s["city"]:<12} {s["avg_prior90"]:.2f}→{s["avg_recent90"]:.2f} (Δ−{drop:.2f}) · {s["n_recent90"]} reviews · theme: {s["top_theme"] or "—"}')

    # Low-star theme rollup across all locations
    print('\n' + '=' * 70)
    print('LOW-STAR (≤3) THEMES ACROSS ALL 18,203 REVIEWS')
    print('=' * 70)
    all_themes = Counter()
    for r in rows:
        if r['stars'] and r['stars'] <= 3 and r['text']:
            for k, rx in THEMES.items():
                if rx.search(r['text']):
                    all_themes[k] += 1
    low_total = sum(1 for r in rows if r['stars'] and r['stars'] <= 3 and r['text'])
    print(f'  {low_total} low-star reviews with text · theme matches:')
    for k, v in all_themes.most_common():
        print(f'    {k:<14} {v:>4}  ({v/low_total*100:.0f}%)')


if __name__ == '__main__':
    main()
