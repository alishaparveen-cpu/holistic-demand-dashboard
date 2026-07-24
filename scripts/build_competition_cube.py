#!/usr/bin/env python3
"""Build data_competition.json — the cube behind the Competition Intelligence view.
Per category (SH now; STI/MH when crawled): national / city / clinic rollups with
funnel metrics + competitor mix + top rivals (with Google Maps links) + verdicts + why-tags.
"""
import os, csv, json, datetime, statistics as st
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = datetime.date(2026, 7, 24)
COMPOSE = json.load(open(os.path.join(ROOT, 'data_campaign_compose.json')))
NW = len(COMPOSE['_meta']['weeks'])
ALT = ('Ayurvedic', 'Unani', 'Homeopathic')
import urllib.parse
def MAPS(pid, name='', city=''):
    # ChIJ… = real Place ID → query_place_id; numeric = Google CID → ?cid=; else name search
    if pid and str(pid).startswith('ChIJ'):
        return 'https://www.google.com/maps/search/?api=1&query=' + urllib.parse.quote(name or 'place') + '&query_place_id=' + pid
    if pid and str(pid).isdigit():
        return f'https://www.google.com/maps?cid={pid}'
    if name:
        return 'https://www.google.com/maps/search/?api=1&query=' + urllib.parse.quote(f'{name} {city}')
    return ''

DFS = json.load(open(os.path.join(ROOT, 'data_serp_dfs.json'))) if os.path.exists(os.path.join(ROOT, 'data_serp_dfs.json')) else {}
_CATS = ('SH', 'STI', 'MH')
def _nm0(s): return ''.join(ch for ch in str(s).lower() if ch.isalnum())
# GMB category per competitor NAME from the crawl — used to enrich the SERP grid (grid rows lack category)
DFS_CATMAP = {}
for _c in _CATS:
    for _e in DFS.get(_c, {}).values():
        for _x in _e.get('competitors', []):
            if _x.get('name') and _x.get('category'):
                DFS_CATMAP.setdefault((_c, _nm0(_x['name'])), _x['category'])
def our_listing(cat, key):
    """Our own Allo Google-Maps listing from the fresh crawl. Rank is category-specific (position in
    THIS category's search); review count/Place ID are the same listing → borrow from any category if the
    home-category search didn't surface us."""
    own = (DFS.get(cat, {}).get(key) or {}).get('our') or {}
    rank, pid, rating = own.get('pos'), own.get('place_id'), own.get('rating')
    reviews = int(own['reviews']) if own.get('reviews') else None
    if reviews is None or pid is None:
        for c in _CATS:
            o = (DFS.get(c, {}).get(key) or {}).get('our') or {}
            if o.get('reviews') and reviews is None: reviews, rating = int(o['reviews']), rating or o.get('rating')
            if o.get('place_id') and pid is None: pid = o['place_id']
    if rank is None and pid is None and reviews is None: return None
    return dict(reviews=reviews, rating=rating, rank=rank, pid=pid)

def _n(s): return ''.join(ch for ch in str(s).lower() if ch.isalnum())
def dfs_km(cat, key, name):
    """Recover a competitor's exact distance from the crawl (geographic → same across categories)."""
    tgt = _n(name)
    if not tgt: return None
    for c in [cat] + [x for x in _CATS if x != cat]:
        for cc in (DFS.get(c, {}).get(key) or {}).get('competitors', []):
            if cc.get('km') is None: continue
            nm = _n(cc.get('name', ''))
            if nm[:18] == tgt[:18] or (len(tgt) > 6 and (tgt in nm or nm in tgt)):
                return round(cc['km'], 1)
    return None

def num(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d

def funnel(city, cat):
    c = COMPOSE.get(city)
    if not c: return None
    wa = lambda f, p: sum((x.get(f, 0) or 0) for x in c['acq'] if p(x)) / NW
    wf = lambda f, p: sum((x.get(f, 0) or 0) for x in c['fun'] if p(x)) / NW
    ap = lambda x: x['cat'] == cat and x['mt'] == 'Exact-Local'
    fp = lambda x: x['cat'] == cat and (x['ch'], x['med']) != ('Google', 'Web')
    im, el, ck, lc = wa('impr', ap), wa('elig', ap), wa('click', ap), wa('locclick', ap)
    ld, bk, dn, sp = wf('lead', fp), wf('bk', fp), wf('dn', fp), wa('sp', ap)
    r = lambda n, dd: n / dd if dd else 0
    return dict(spend=round(sp), leads=round(ld), clicks=round(ck), locclicks=round(lc),
                mkt=round(el), impr=round(im), bookings=round(bk), done=round(dn),
                IS=round(r(im, el), 3), locpct=round(r(lc, ck), 3), loc2ld=round(r(ld, lc), 3),
                ld2bk=round(r(bk, ld), 3), bk2dn=round(r(dn, bk), 3),
                cpl=round(r(sp, ld)), cpc=round(r(sp, ck)), cplc=round(r(sp, lc)))

def load_pathy():
    out = {}
    for fn in ('data_serp_pathy.tsv', 'data_serp_pathy_v2.tsv'):
        p = os.path.join(ROOT, fn)
        if os.path.exists(p):
            for r in csv.DictReader(open(p), delimiter='\t'): out[r['place_id']] = r['pathy']
    return out
PATHY = load_pathy()
def norm(p): return p if p in ('Allopathic',) + ALT + ('Non-medical', 'Mixed') else 'Thin'

# ── SH from the fresh crawl: relevance filter (real men's-SH rival vs tangential) + pathy classifier ──
def _nm(s): return ''.join(ch for ch in str(s).lower() if ch.isalnum())
def load_name_pathy():
    """Verified pathy keyed by clinic NAME (fresh crawl uses ChIJ ids, not the old numeric CIDs)."""
    out = {}
    for fn in ('data_serp_pathy.tsv', 'data_serp_pathy_v2.tsv', 'data_serp_sh_pathy.tsv'):
        p = os.path.join(ROOT, fn)
        if os.path.exists(p):
            for r in csv.DictReader(open(p), delimiter='\t'):
                if r.get('name') and r.get('pathy'): out[_nm(r['name'])] = r['pathy']
    return out
NAME_PATHY = load_name_pathy()
def load_nonrival():
    """Web-verified non-rivals (gynae/fertility/diabetes/general that only tangentially rank for 'sexologist')."""
    out = set(); p = os.path.join(ROOT, 'data_serp_sh_pathy.tsv')
    if os.path.exists(p):
        for r in csv.DictReader(open(p), delimiter='\t'):
            if r.get('rival', '').lower() == 'no' and r.get('name'): out.add(_nm(r['name']))
    return out
NONRIVAL = load_nonrival()
SH_SIGNAL = ('sexolog', 'androl', "men's health", 'mens health', 'urolog', 'sexual', 'sex care',
             'sex clinic', 'sex problem', 'gupt')                                    # positive men's-SH rival
SH_DROP = ('gyneco', 'obstetric', 'fertility', 'maternity', 'women', 'ivf', 'dermat', 'skin', 'laser',
           'endocrin', 'diabet', 'thyroid', 'dental', 'dentist', 'ophthal', ' ent ', 'cardio', 'heart',
           'ortho', 'physiothe', 'pediatric', 'paediatric', 'nephro', 'kidney', 'de-addiction', 'deaddiction')
def sh_relevant(name, category):
    """True = a genuine men's sexual-health rival (eligible to be the #1 rival)."""
    if _nm(name) in NONRIVAL: return False                         # web-verified tangential (gynae/fertility/diabetes/general)
    s = (str(name) + ' ' + str(category or '')).lower()
    if any(k in s for k in SH_SIGNAL): return True
    if any(k in s for k in SH_DROP): return False
    return None                                                    # generic (Doctor/Clinic) — keep in list, not a headline rival
def sh_pathy(name, category):
    p = NAME_PATHY.get(_nm(name))
    if p: return p
    s = (str(name) + ' ' + str(category or '')).lower()
    if 'ayurved' in s or 'ayush' in s or 'kerala ayurveda' in s: return 'Ayurvedic'
    if 'unani' in s or 'hakim' in s: return 'Unani'
    if 'homeo' in s or 'homoeo' in s: return 'Homeopathic'
    return 'Allopathic'                                            # default (verified later); most MBBS/andrology sexologists
# clinics that are CLOSED — excluded from the cube (user-confirmed + known)
CLOSED = {'Delhi NCR|Greater Kailash', 'Delhi NCR|Gurugram', 'Hyderabad|Attapur', 'Vijayawada|Suryaraopeta'}

def load_gmb():
    """Per-clinic recent GMB profile. GBP lags ~1 wk → drop the newest week, average the next
    up-to-4 mature weeks (days>=6). Returns {City|Loc: {searches,calls,website,directions,interactions}/wk}."""
    p = os.path.join(ROOT, 'data_gmb_comp.json')
    if not os.path.exists(p): return {}
    d = json.load(open(p)); nw = len(d['_meta']['weeks']); out = {}
    for key, e in d.items():
        if key == '_meta': continue
        days = e.get('days', [7] * nw)
        idx = [i for i in range(1, nw) if days[i] >= 6][:4]          # skip newest (immature), take 4 mature
        if not idx: idx = list(range(1, min(5, nw)))
        avg = lambda f: round(sum(e.get(f, [0] * nw)[i] for i in idx) / len(idx))
        out[key] = dict(searches=avg('searches'), calls=avg('calls'), website=avg('website'),
                        directions=avg('directions'), interactions=avg('interactions'), mature_wks=len(idx))
    return out
GMB = load_gmb()

# ─── per-category taxonomy: type label → parent "kind"; display order + colours drive the UI ───
TAX = {
  'SH': {
    'kind': {'Allopathic':'Allopathic','Ayurvedic':'Alternate medicine','Unani':'Alternate medicine',
             'Homeopathic':'Alternate medicine','Non-medical':'Non-medical','Mixed':'Mixed / unclear','Thin':'Other'},
    'kindOrder': ['Allopathic','Alternate medicine','Non-medical','Mixed / unclear','Other'],
    'typeColor': {'Allopathic':'#2C6CAE','Ayurvedic':'#7D5BA6','Unani':'#2A9D8F','Homeopathic':'#C86B9E',
                  'Non-medical':'#B8862E','Mixed':'#B8503C','Thin':'#9AA6B5'},
    'kindColor': {'Allopathic':'#2C6CAE','Alternate medicine':'#7D5BA6','Non-medical':'#B8862E','Mixed / unclear':'#B8503C','Other':'#9AA6B5'}},
  'STI': {
    'kind': {'Diagnostic lab':'Lab-based','STD/HIV clinic':'Specialist clinic','Sexologist':'Specialist clinic',
             'Gynae / Fertility':'Specialist clinic','Hospital / Clinic':'Hospital / general','Other':'Other'},
    'kindOrder': ['Lab-based','Specialist clinic','Hospital / general','Other'],
    'typeColor': {'Diagnostic lab':'#2A9D8F','STD/HIV clinic':'#C0392B','Sexologist':'#7D5BA6',
                  'Gynae / Fertility':'#C86B9E','Hospital / Clinic':'#2C6CAE','Other':'#9AA6B5'},
    'kindColor': {'Lab-based':'#2A9D8F','Specialist clinic':'#7D5BA6','Hospital / general':'#2C6CAE','Other':'#9AA6B5'}},
  'MH': {
    'kind': {'Psychiatrist':'Medical psychiatry','Clinic / Doctor':'Medical psychiatry',
             'Therapist / Counsellor':'Therapy / counselling','Hospital / Psych hospital':'Hospital / rehab','Other':'Other'},
    'kindOrder': ['Medical psychiatry','Therapy / counselling','Hospital / rehab','Other'],
    'typeColor': {'Psychiatrist':'#2C6CAE','Therapist / Counsellor':'#7D5BA6','Hospital / Psych hospital':'#C0392B',
                  'Clinic / Doctor':'#2A9D8F','Other':'#9AA6B5'},
    'kindColor': {'Medical psychiatry':'#2C6CAE','Therapy / counselling':'#7D5BA6','Hospital / rehab':'#C0392B','Other':'#9AA6B5'}},
}
def kind_of(cat, t): return TAX[cat]['kind'].get(t, 'Other')

# STI/MH facility type ← Google-Maps category (order matters: check hospital before psychiatrist, lab before clinic)
STI_RULES = [
  ('Diagnostic lab', ['diagnostic','blood testing','patholog','laborator','medical lab','imaging','x-ray','scan','hiv testing','std testing service']),
  ('STD/HIV clinic', ['std clinic','sexually transmitted','infectious disease']),
  ('Sexologist', ['sexolog']),
  ('Gynae / Fertility', ['gyneco','obstetric','women','fertility','maternity','ivf']),
  ('Hospital / Clinic', ['hospital','medical clinic','medical cent','clinic','doctor','physician','polyclinic','health']),
]
MH_RULES = [
  ('Hospital / Psych hospital', ['psychiatric hospital','mental hospital','psychiatry hospital','hospital','rehabilitation','rehab',
                                 'nursing home','alcoholism','de-addiction','deaddiction','recovery']),
  ('Psychiatrist', ['psychiatr']),
  ('Therapist / Counsellor', ['psycholog','psychotherap','counsel','therapist','mental health service','wellness','life coach',
                              'marriage','relationship','family counsel','de-addiction']),
  ('Clinic / Doctor', ['homeopath','medical clinic','medical cent','clinic','doctor','physician','neurolog']),
]
# genuine MH signal / generic-medical — a valid #1 MH rival must match one of these …
MH_SIGNAL = ('psychiatr', 'psycholog', 'psychotherap', 'counsel', 'therap', 'mental', 'rehab', 'de-addiction',
             'deaddiction', 'alcohol', 'neuro', 'marriage', 'life coach', 'wellness', 'homeopath')
MH_GENERIC = ('doctor', 'medical clinic', 'medical cent', 'hospital', 'clinic', 'physician')
# … and must NOT match these off-topic categories (checked first, so 'career counseling' etc. are excluded)
MH_DROP = ('dermat', 'gyneco', 'obstetric', 'women', 'maternity', 'ent specialist', 'diabet', 'thyroid', 'pulmon',
           'gastro', 'cardio', 'ortho', 'nephro', 'urolog', 'ophthal', 'physiothe', 'pediatric', 'paediatric', 'surgeon',
           'imaging', 'diagnostic center', 'speech & hearing', 'emergency', 'research institute',
           'educational consultant', 'career counsel', 'student career', 'career guidance', 'spa', 'beauty', 'salon',
           'coaching cent', 'tuition', 'training institute', 'astrolog', 'yoga', 'fitness', 'gym')
# STI/MH type = the raw Google-Maps category (no custom buckets / no 'Other'). SH keeps pathy.
PALETTE = ['#2C6CAE', '#7D5BA6', '#2A9D8F', '#C86B9E', '#B8862E', '#C0392B', '#3A7CA5', '#8E44AD',
           '#16A085', '#D35400', '#2980B9', '#27AE60', '#A93226', '#5D6D7E', '#AF7AC5', '#1ABC9C', '#E67E22']
def cat_relevant(cat, name, category):
    """False = tangential (won't be the #1 rival). STI: any lab/clinic counts. MH: must be a real
    mental-health listing (drop dermatology/gynae/ENT/etc. and category-less)."""
    if cat != 'MH': return True
    s = ((category or '') + ' ' + (name or '')).lower()
    if any(k in s for k in MH_DROP): return False                       # clearly off-topic (derm/education/spa/…)
    if any(k in s for k in MH_SIGNAL): return True                      # clearly a mental-health listing
    if category and not any(k in s for k in MH_GENERIC): return False   # a non-MH category with no MH signal
    return None                                                        # unknown (e.g. grid rows have no category) → keep
def build_tax(cube, cat):
    """Dynamic taxonomy for STI/MH: each GMB category is its own type; colours from a palette by frequency."""
    freq = {}
    for v in cube[cat]['clinics'].values():
        for c in v['competitors']:
            freq[c['pathy']] = freq.get(c['pathy'], 0) + 1
    order = sorted(freq, key=lambda k: -freq[k])
    color = {c: PALETTE[i % len(PALETTE)] for i, c in enumerate(order)}
    return {'kind': {c: c for c in order}, 'kindOrder': order, 'typeColor': color, 'kindColor': color}

def load_rank_est():
    """Our estimated local-pack rank per clinic — grid-averaged from our own SERP tracking
    (serp_analyses via data_serp_competitors.tsv). None/0 = not ranking; ~1 = top of pack; >1.5 = outranked."""
    out = {}
    p = os.path.join(ROOT, 'data_serp_competitors.tsv')
    if os.path.exists(p):
        for r in csv.DictReader(open(p), delimiter='\t'):
            k = (r.get('cat', 'SH'), _nm(r.get('city', '')), _nm(r.get('locality', '')))
            if k not in out and r.get('our_avg_rank'):
                try: out[k] = round(float(r['our_avg_rank']), 1)
                except ValueError: pass
    return out
RANK_EST = load_rank_est()

def why_tags(our, orank, top, cat):
    """Reviews are the durable moat; rank (grid-avg estimate) sharpens the call.
    orank None/0 = not ranking · ≤1.5 = top of pack · >1.5 = outranked."""
    ranked = bool(orank) and orank > 0
    top1 = ranked and orank <= 1.5
    rival_ahead = top['reviews'] > our
    tags = []
    if not rival_ahead:
        tags.append('winning')
        if ranked and not top1: tags.append('have-reviews-but-outranked')   # more reviews but a rival ranks above → bid/GMB fix
    elif top1:
        tags.append('defend')                                               # rank ~#1 now but out-reviewed → protect the lead
    else:
        tags.append('beaten:' + top['pathy'])
        if our < top['reviews'] * 0.5: tags.append('review-gap')
    return tags

def clinic_verdict(our, orank, top, tags, cat):
    t = top['pathy']
    if 'have-reviews-but-outranked' in tags: return ('OUTRANK — we have the reviews, fix GMB/bid', 'outrank')
    if 'defend' in tags: return (f'DEFEND — rank ~#1 but out-reviewed ({top["reviews"]} vs {our})', 'defend')
    if 'winning' in tags: return ('Winning — hold + keep reviews', 'win')
    if 'review-gap' in tags: return (f'BUILD REVIEWS — {t} rival far ahead ({top["reviews"]} vs {our})', 'reviews')
    return (f'BUILD REVIEWS — {t} rival leads {top["reviews"]} vs {our}', 'reviews')

def _rollup(cat, cube, clinics, citymap):
    cities = {}
    for city, keys in citymap.items():
        f = funnel(city, cat) or {}
        allc = []
        for k in keys: allc += clinics[k]['competitors']
        seen = {}
        for c in allc:
            if c['name'] not in seen or c['reviews'] > seen[c['name']]['reviews']: seen[c['name']] = c
        rivals = sorted(seen.values(), key=lambda c: -c['reviews'])[:5]
        our = max((clinics[k]['our_reviews'] for k in keys), default=0)
        n = len(rivals) or 1
        cnt = defaultdict(int)
        for c in rivals: cnt[c['pathy']] += 1
        wins = sum(1 for k in keys if 'winning' in clinics[k]['tags'])
        cities[city] = dict(funnel=f, our_reviews=our, top_rivals=rivals,
                            mix={p: round(cnt[p] / n, 2) for p in set(cnt)},
                            clinics=keys, wins=wins, nclinic=len(keys),
                            winrate=round(wins / len(keys), 2))
    allkeys = list(clinics)
    natwins = sum(1 for k in allkeys if 'winning' in clinics[k]['tags'])
    tagcount = defaultdict(int)
    for k in allkeys:
        for t in clinics[k]['tags']: tagcount[t] += 1
    cube[cat] = dict(clinics=clinics, cities=cities,
                     national=dict(nclinic=len(allkeys), wins=natwins,
                                   winrate=round(natwins / max(1, len(allkeys)), 2),
                                   tags=dict(tagcount)))

def _type_of(cat, name, category, pid):
    return (NAME_PATHY.get(_nm(name)) or norm(PATHY.get(pid))) if cat == 'SH' else (category or 'Uncategorised')
def _rel_of(cat, name, category):
    return sh_relevant(name, category) if cat == 'SH' else cat_relevant(cat, name, category)

def build_cat_grid(cat, rows, cube):
    """Build a category from our own SERP grid (serp_analyses / data_serp_competitors.tsv) —
    market-comprehensive, matching the Field Data Dashboard. The #1 rival is the most grid-DOMINANT
    relevant competitor by APPEARANCES (share of local searches it ranks in), which surfaces the real
    threats and demotes big-review non-competitors. Merges the single-point crawl (incl. supplementary
    treatment/therapy keywords) so keyword-specific rivals aren't lost, and falls back to it for clinics
    the grid hasn't tracked yet. SH type = pathy; STI/MH type = raw GMB category."""
    byclinic = defaultdict(list)
    for r in rows:
        if r.get('cat', 'SH') != cat: continue
        byclinic[(r['city'], r['locality'])].append(r)
    clinics = {}; citymap = defaultdict(list)
    for (city, loc), lst in byclinic.items():
        key = f'{city}|{loc}'
        if key in CLOSED: continue
        our = max((int(num(r.get('our_reviews'))) for r in lst), default=0)
        rank_est = RANK_EST.get((cat, _nm(city), _nm(loc)))
        grid_n = max((int(num(r.get('clinic_searches'))) for r in lst), default=0)   # grid points for this clinic
        comps_all = []
        for r in lst:
            name = r.get('comp_name')
            if not name: continue
            pid = r.get('place_id', '')
            app = int(num(r.get('appearances')))
            gcat = r.get('category') or DFS_CATMAP.get((cat, _nm(name)))   # grid lacks category → borrow from crawl by name
            comps_all.append(dict(name=name, pathy=_type_of(cat, name, gcat, pid), category=gcat,
                reviews=int(num(r.get('reviews'))), rating=num(r.get('rating')) or None,
                km=round(num(r['clinic_km']), 1) if r.get('clinic_km') else None,
                appearances=app, dompct=(round(app / grid_n * 100) if grid_n else None),
                pos=round(num(r.get('avg_pos')), 1), ads=str(r.get('ever_sponsored', '')).lower() == 'true',
                rel=_rel_of(cat, name, r.get('category')), maps=MAPS(pid, name, city)))
        # merge single-point crawl competitors (esp. supplementary treatment/therapy keywords) not in the grid
        seen = {_nm(c['name']) for c in comps_all}
        for c in DFS.get(cat, {}).get(key, {}).get('competitors', []):
            if not c.get('name') or _nm(c['name']) in seen: continue
            seen.add(_nm(c['name']))
            comps_all.append(dict(name=c['name'], pathy=_type_of(cat, c['name'], c.get('category'), ''),
                category=(c.get('category') or None), reviews=int(c['reviews']) if c.get('reviews') else 0,
                rating=c.get('rating'), km=round(c['km'], 1) if c.get('km') is not None else None,
                appearances=0, dompct=None, pos=c.get('pos'), ads=bool(c.get('is_paid')),
                rel=_rel_of(cat, c['name'], c.get('category')), maps=MAPS(c.get('place_id'), c['name'], city)))
        if not comps_all: continue
        # #1 rival = most grid-dominant relevant competitor (appearances), reviews as tiebreak
        rel = [c for c in comps_all if c['rel'] is True] or [c for c in comps_all if c['rel'] is not False] or comps_all
        rel.sort(key=lambda c: (-c['appearances'], -c['reviews']))
        rest = sorted([c for c in comps_all if c is not rel[0]], key=lambda c: -c['appearances'])
        comps = [rel[0]] + rest[:6]
        top = comps[0]
        tags = why_tags(our, rank_est, top, cat)
        vtext, vkind = clinic_verdict(our, rank_est, top, tags, cat)
        clinics[key] = dict(city=city, loc=loc, our_reviews=our, our_rank=rank_est or 0, rank_est=rank_est,
                            our_maps=MAPS('', f'Allo Health {loc}', city),
                            competitors=comps, tags=tags, verdict=vtext, vkind=vkind, gmb=GMB.get(key))
        citymap[city].append(key)
    # clinics entirely absent from the SERP grid → build from the single-point crawl so none are missing
    for k, e in DFS.get(cat, {}).items():
        if k in clinics or '|' not in k or k in CLOSED: continue
        city, loc = k.split('|', 1)
        comps_all = []
        for c in e.get('competitors', []):
            if not c.get('name'): continue
            comps_all.append(dict(name=c['name'], pathy=_type_of(cat, c['name'], c.get('category'), ''),
                category=(c.get('category') or None), reviews=int(c['reviews']) if c.get('reviews') else 0, rating=c.get('rating'),
                km=round(c['km'], 1) if c.get('km') is not None else None, appearances=0, dompct=None, pos=c.get('pos'),
                ads=bool(c.get('is_paid')), rel=_rel_of(cat, c['name'], c.get('category')), maps=MAPS(c.get('place_id'), c['name'], city)))
        if not comps_all: continue
        rel = [c for c in comps_all if c['rel'] is True] or [c for c in comps_all if c['rel'] is not False] or comps_all
        rel.sort(key=lambda c: -c['reviews'])
        comps = [rel[0]] + sorted([c for c in comps_all if c is not rel[0]], key=lambda c: -c['reviews'])[:6]
        top = comps[0]
        ol = our_listing(cat, k); our = ol['reviews'] if ol and ol['reviews'] is not None else 0
        rank_est = RANK_EST.get((cat, _nm(city), _nm(loc)))
        tags = why_tags(our, rank_est, top, cat); vtext, vkind = clinic_verdict(our, rank_est, top, tags, cat)
        clinics[k] = dict(city=city, loc=loc, our_reviews=our, our_rank=rank_est or 0, rank_est=rank_est,
                          our_maps=MAPS(ol['pid'] if ol else '', f'Allo Health {loc}', city),
                          competitors=comps, tags=tags, verdict=vtext, vkind=vkind, gmb=GMB.get(k))
        citymap[city].append(k)
    _rollup(cat, cube, clinics, citymap)

def build_cat_dfs(cat, cube):
    """STI / MH: built straight from the fresh Maps crawl — facility-type from the Google-Maps category,
    exact distances, true rank, current reviews, real Place IDs."""
    clinics = {}; citymap = defaultdict(list)
    for key, e in DFS.get(cat, {}).items():
        if '|' not in key or key in CLOSED: continue
        city, loc = key.split('|', 1)
        ol = our_listing(cat, key)
        our = ol['reviews'] if ol and ol['reviews'] is not None else 0
        orank = RANK_EST.get((cat, _nm(city), _nm(loc)))   # reliable grid-avg rank estimate
        our_pid = ol['pid'] if ol else ''
        comps_all = []
        for c in e.get('competitors', []):
            if not c.get('name'): continue
            rev = c.get('reviews')
            comps_all.append(dict(name=c['name'], pathy=(c.get('category') or 'Uncategorised'),
                                  category=c.get('category'), reviews=int(rev) if rev else 0,
                                  rating=c.get('rating'), km=round(c['km'], 1) if c.get('km') is not None else None,
                                  pos=c.get('pos'), ads=bool(c.get('is_paid')), rel=cat_relevant(cat, c['name'], c.get('category')),
                                  maps=MAPS(c.get('place_id'), c['name'], city)))
        if not comps_all: continue
        # headline #1 rival = highest-review RELEVANT competitor; tangential specialists stay in list but not as headline
        rel = [c for c in comps_all if c['rel']] or comps_all
        rel.sort(key=lambda c: -c['reviews'])
        rest = sorted([c for c in comps_all if c is not rel[0]], key=lambda c: -c['reviews'])
        comps = [rel[0]] + rest[:6]
        top = comps[0]
        tags = why_tags(our, orank, top, cat)
        vtext, vkind = clinic_verdict(our, orank, top, tags, cat)
        clinics[key] = dict(city=city, loc=loc, our_reviews=our, our_rank=orank or 0, rank_est=orank,
                            our_maps=MAPS(our_pid, f'Allo Health {loc}', city),
                            our_rating=(ol.get('rating') if ol else None),
                            competitors=comps, tags=tags, verdict=vtext, vkind=vkind, gmb=GMB.get(key))
        citymap[city].append(key)
    _rollup(cat, cube, clinics, citymap)

def main():
    rows = list(csv.DictReader(open(os.path.join(ROOT, 'data_serp_competitors.tsv')), delimiter='\t'))
    cube = {'_meta': {'built': str(TODAY), 'cats': [], 'tax': TAX}}
    for cat in ('SH', 'STI', 'MH'):
        build_cat_grid(cat, rows, cube); cube['_meta']['cats'].append(cat)
        if cat != 'SH':
            cube['_meta']['tax'][cat] = build_tax(cube, cat)   # STI/MH type = raw GMB category (dynamic)
    json.dump(cube, open(os.path.join(ROOT, 'data_competition.json'), 'w'), separators=(',', ':'))
    print('wrote data_competition.json · cats', cube['_meta']['cats'],
          '·', {c: len(cube[c]['clinics']) for c in cube['_meta']['cats']}, 'clinics')

if __name__ == '__main__':
    main()
