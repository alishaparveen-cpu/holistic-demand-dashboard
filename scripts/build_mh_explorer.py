#!/usr/bin/env python3
"""Regenerate the MH Launch Scoring Explorer with the redesigned model.

Model (all factors → percentile rank, recomputed live within the selected tier):
  Market            = City search demand (city-level)  +  Local competitor density (locality proxy)
  Competitive openness = Few strong rivals (inverse count of 100+-review rivals; threshold is a live slider)
  Our strength      = Our reviews  +  Our GMB discovery (searches)  +  Our GMB leads (calls+website+directions)

Tier filter (All / Tier 1 / Tier 2) refilters the clinic set AND recomputes every percentile within it,
so Tier-1 clinics are ranked against each other, then Tier-2 separately.
"""
import json, os

ROOT = '/mnt/user-data/uploads/hdd-live'
OUT  = '/mnt/user-data/outputs/mh_launch_explorer.html'
def P(f): return os.path.join(ROOT, f)
def norm(s): return str(s).strip().lower()
def dedup_comps(lst):
    """Drop duplicate rivals with the SAME name (grid rows lack place_id, so the same business can appear
    at two grid cells — e.g. 'Dr. Fayyaz' with 569 reviews AND a 0-review echo). Keep the richest record."""
    best, out = {}, []
    for x in lst:
        nm = (x.get('name') or '').strip().lower()
        if not nm:
            out.append(x); continue
        j = best.get(nm)
        if j is None:
            best[nm] = len(out); out.append(x)
        elif int(x.get('reviews') or 0) > int(out[j].get('reviews') or 0):
            out[j] = x                      # replace with the higher-review copy
    return out

d   = json.load(open(P('data_competition.json')))
mh  = d['MH']['clinics']

# guard: drop casing/duplicate clinic records (e.g. 'MUMBAI|Vashi' duplicating 'Navi Mumbai|Vashi'),
# which would otherwise surface as a phantom single-clinic city. Two records with the SAME locality name
# AND the same our_reviews are the same clinic; keep the properly-cased city over an ALL-CAPS duplicate.
_seen, _clean = {}, {}
for _k, _c in mh.items():
    _sig = (str(_c.get('loc', '')).strip().lower(), int(_c.get('our_reviews') or 0))
    _prev = _seen.get(_sig)
    if _prev is not None:
        _pc, _tc = mh[_prev].get('city', ''), _c.get('city', '')
        if _tc.isupper() and not _pc.isupper():
            continue                       # this one is the ALL-CAPS dupe → skip
        if _pc.isupper() and not _tc.isupper():
            _clean.pop(_prev, None)         # earlier ALL-CAPS dupe → drop it, keep this
        else:
            continue                       # ambiguous → keep first seen
    _seen[_sig] = _k
    _clean[_k] = _c
mh = _clean


geo = json.load(open(P('data_mh_demand_geo.json')))

# per-clinic GMB-SOURCE leads, LAST-4-WEEK average — from data_leads.json (fresh, current to this week).
# Each clinic's 'cells' are source×medium rows; ch=='GMB' rows carry weekly lead counts in 'w' (newest first).
# Leads carry a 'cat' vertical tag (SH / MH / STI / …), so GMB leads CAN be split by vertical. GMB *discovery*
# (searches) cannot — it's one clinic listing. So: clinic-wide GMB leads (any cat) feed nothing directly; the
# SH-specific factor uses cat=='SH' leads, and MH standing uses MH-specific rank/share + clinic-wide discovery.
gmb_leads_map = {}   # clinic-wide GMB leads (all cats) — kept for reference/verdicts
sh_leads_map = {}    # SH-tagged GMB leads only → the SH-protection factor
_leads = json.load(open(P('data_leads.json')))
def _lead4(cells, only_cat=None):
    _tot = [0, 0, 0, 0]
    for _x in cells:
        if _x.get('ch') != 'GMB': continue
        if only_cat is not None and _x.get('cat') != only_cat: continue
        _w = _x.get('w') or []
        for _i in range(4):
            if _i < len(_w): _tot[_i] += _w[_i] or 0
    return round(sum(_tot) / 4, 1)
for _key, _c in _leads.items():
    if _key == '_meta': continue
    gmb_leads_map[norm(_key)] = _lead4(_c.get('cells', []))
    sh_leads_map[norm(_key)]  = _lead4(_c.get('cells', []), only_cat='SH')

# ── SH (sexual-health) standing per clinic — feeds the "SH stays safe" factor (all SH-specific, no overlap). ──
# Launching MH shouldn't cannibalise the existing SH business; a clinic is SAFE where our SH is entrenched
# (near #1 locally, owns the review base, healthy SH-TAGGED lead flow). Density is carried for context and is a
# tunable sub-bucket (sign is the user's to set). All 79 MH clinics also carry SH data.
_sh = d.get('SH', {}).get('clinics', {})
sh_metrics = {}
for _k, _c in _sh.items():
    _our = int(_c.get('our_reviews') or 0)
    _rank = _c.get('our_rank') or _c.get('rank_est')          # ~1.0 = #1 in local pack (lower is better)
    _leads = sh_leads_map.get(norm(_k), 0)                     # SH-tagged GMB leads/wk (cat=='SH') — genuinely SH-specific
    _riv = dedup_comps([x for x in _c.get('competitors', []) if x.get('rel') is not False and x.get('in_radius')])
    _rl = sorted([int(x.get('reviews') or 0) for x in _riv], reverse=True)                      # SH rival review counts (≤5km)
    _rivrev = sum(_rl)
    _share = (_our / (_our + _rivrev)) if (_our + _rivrev) > 0 else None                        # our local SH review share
    _srivals = [dict(name=x.get('name'), reviews=int(x.get('reviews') or 0), rating=x.get('rating'),
                     km=x.get('km'), near=bool(x.get('in_radius')), maps=x.get('maps'))
                for x in sorted(_riv, key=lambda z: -(z.get('reviews') or 0))[:8]]
    sh_metrics[_k] = dict(rank=_rank, share=_share, leads=_leads, rev=_rl, rivals=_srivals,
                          maps=_c.get('our_maps'), our=_our)                                       # rev = SH rival reviews (live bar)

# city → total geo-attributed monthly MH search volume (casing-normalised: fixes the MUMBAI/Mumbai split)
geo_sv = {}
for city, cats in geo.items():
    if city == '_national': continue
    geo_sv[norm(city)] = sum(v for kw in cats.values() for v in kw.values())

# ── Practo LOCALITY demand: zone-level General-Psychiatry pageviews, matched to clinic localities. ──
# Used as a BOUNDED within-city tilt on top of the city search-volume base — never a replacement.
# Practo pageviews measure Practo's own traffic footprint (Thane reads a spurious 55), so the tilt is
# sqrt-damped and clamped to ±40%: it differentiates localities WITHIN a city without letting a noisy or
# sparse zone crater a clinic or distort cross-city ordering. Unmatched clinics sit at the city baseline.
import math as _math
try:
    _practo = json.load(open(P('data_practo_demand.json')))
except Exception:
    _practo = {'byclinic': {}, 'meta': {}, 'citypv': {}}
practo_pv = _practo.get('byclinic', {})          # clinic_key -> zone pageviews
practo_meta = _practo.get('meta', {})            # clinic_key -> {zone, zone_pv, city_pv}
# per-city mean of MATCHED clinics' zone pageviews (need >=2 matched in a city for any tilt to bite)
_pv_by_city = {}
for _k, _pv in practo_pv.items():
    _pv_by_city.setdefault(_k.split('|')[0], []).append(_pv)
practo_city_mean = {_c: (sum(_v) / len(_v)) for _c, _v in _pv_by_city.items()}
def practo_tilt(key, city):
    """Bounded within-city demand multiplier from Practo locality pageviews (1.0 if unmatched / single-match city)."""
    pv = practo_pv.get(key)
    m = practo_city_mean.get(city, 0)
    if not pv or m <= 0 or len(_pv_by_city.get(city, [])) < 2:
        return 1.0
    return max(0.7, min(1.4, _math.sqrt(pv / m)))

# lead-history aliases: a clinic renamed/relocated keeps its old-name lead tracking.
# Bilekahalli is the current name of the clinic Allo historically tracked as "Arekere".
LEADS_ALIAS = {'bangalore|bilekahalli': 'bangalore|arekere'}

T1 = {'chennai', 'mumbai', 'navi mumbai', 'bangalore', 'hyderabad', 'pune'}
STRONG = 100  # default "strong rival" review bar (user-tunable slider)

def hhi_klass(revs):
    tot = sum(revs) or 1
    hhi = sum((r / tot) ** 2 for r in revs)
    n = len(revs); top = revs[0] if revs else 0; share = top / tot
    if n == 0:            return 0.0, 'Open field (no rival)'
    if n == 1:            return round(hhi, 3), 'Monopoly (1 dominant)'
    if share >= 0.6:      return round(hhi, 3), 'Monopoly (1 dominant)'
    if share >= 0.4:      return round(hhi, 3), 'Giant + long tail'
    if hhi >= 0.25:       return round(hhi, 3), 'Semi-concentrated'
    return round(hhi, 3), 'Fragmented (up for grabs)'

def rival_class(pathy):
    """Bucket each MH rival into a manager-legible class so competitors can be toggled on/off."""
    p = (pathy or '').lower()
    if 'hospital' in p:                                              return 'hospital'
    if any(t in p for t in ('psychiatr', 'psychoneuro', 'doctor')): return 'psychiatrist'
    if any(t in p for t in ('psycholog', 'counsel', 'therap', 'consultant', 'marriage')): return 'therapy'
    return 'clinic'   # mental health service, medical clinic, wellness centre, homeopath, etc.

clinics = []
for key, c in mh.items():
    city, loc = c['city'], c['loc']
    tier = 'T1' if norm(city) in T1 else 'T2'
    rel  = dedup_comps([x for x in c['competitors'] if x.get('rel') is not False])
    revs = sorted([int(x.get('reviews') or 0) for x in rel], reverse=True)
    gmb  = c.get('gmb') or None
    gmb_srch  = gmb.get('searches') if gmb else None
    _nk = norm(key)
    gmb_leads = gmb_leads_map.get(_nk)
    if gmb_leads is None and _nk in LEADS_ALIAS:
        gmb_leads = gmb_leads_map.get(LEADS_ALIAS[_nk])   # renamed clinic → old-name lead history
    hhi, klass = hhi_klass(revs)
    top_rev = revs[0] if revs else 0
    strong0 = sum(1 for r in revs if r >= STRONG)
    giant   = top_rev >= 1000
    city_sv = geo_sv.get(norm(city))
    _tilt = practo_tilt(key, city)
    demand_val = round(city_sv * _tilt) if city_sv else city_sv   # locality-adjusted demand (Practo-tilted)
    _pm = practo_meta.get(key)
    # full relevant field with class → lets the UI filter by category and recompute everything live
    field = [dict(r=int(x.get('reviews') or 0), k=rival_class(x.get('pathy') or x.get('category')),
                  n=bool(x.get('in_radius')))
             for x in rel]
    rivals = []
    for x in sorted(rel, key=lambda z: -(z.get('reviews') or 0))[:8]:
        rivals.append(dict(name=x['name'], type=(x.get('pathy') or x.get('category') or '—'),
                           k=rival_class(x.get('pathy') or x.get('category')),
                           reviews=int(x.get('reviews') or 0), rating=x.get('rating'),
                           km=x.get('km'), near=bool(x.get('in_radius')), maps=x.get('maps')))
    _our = int(c.get('our_reviews') or 0)
    _beats = sum(1 for r in revs if _our > r)       # local rivals we outrank by review base
    outrank = (_beats / len(revs)) if revs else 1.0  # share of the field we beat (1.0 if unopposed)
    clinics.append(dict(
        key=key, loc=loc, city=city, tier=tier,
        city_sv=city_sv, demand_val=demand_val, ptilt=round(_tilt, 2),
        pzone=(_pm['zone'] if _pm else None), pzone_pv=(_pm['zone_pv'] if _pm else None),
        sh_rank=(sh_metrics.get(key) or {}).get('rank'),
        sh_share=(sh_metrics.get(key) or {}).get('share'),
        sh_leads=(sh_metrics.get(key) or {}).get('leads'),
        sh_rev=(sh_metrics.get(key) or {}).get('rev') or [],
        sh_rivals=(sh_metrics.get(key) or {}).get('rivals') or [],
        sh_maps=(sh_metrics.get(key) or {}).get('maps'),
        sh_our=(sh_metrics.get(key) or {}).get('our'),
        our_maps=c.get('our_maps'),
        density=len(rel),
        our_rev=_our, beats=_beats, outrank=round(outrank, 3),
        gmb_srch=gmb_srch, gmb_leads=gmb_leads,
        rev=revs, field=field,                      # relevant rival reviews (+ per-rival class) → live filter/strong-count
        nriv=len(rel), hhi=hhi, top_rev=top_rev, klass=klass, giant=giant,
        verify_demand=(len(rel) == 0 or (city_sv or 0) < 300),
        verdict=(c.get('verdict') or ''), rivals=rivals))

groups = [
 {"id": "demand", "label": "Demand", "desc": "how much local search demand there is — competition is NOT counted here", "w": 25, "color": "#2c6cae", "subs": [
   {"id": "city", "label": "City search volume", "desc": "geo-attributed monthly MH search volume for the city", "w": 100}]},
 {"id": "competition", "label": "Competition", "desc": "how contested the field is — higher column = MORE competition. Weighted NEGATIVE by default, so a more contested field lowers the score. Each part adds to the intensity (+) or eases it (−).", "w": -25, "color": "#2f7d32", "subs": [
   {"id": "count",  "label": "Rival count (pure)",  "desc": "how many relevant rivals in total.  + = crowded adds to difficulty;  − = a crowded market is validated demand (eases it)", "w": 0},
   {"id": "strong", "label": "Strong-rival count",  "desc": "how many rivals clear the review bar below (set bar to 0 = all rivals).  +100 by default: established rivals are the core of the difficulty", "w": 100},
   {"id": "dom", "label": "Top-rival dominance", "desc": "the #1 rival's SHARE of local reviews — is one giant dominating? (near 100% = a single dominant incumbent; near 0% = no clear leader). This is the 'dominance' read on concentration — who owns the field.  + = a dominant incumbent to target is GOOD;  − = a dominant incumbent is BAD (hard to dislodge)", "w": 0},
   {"id": "div", "label": "Field diversity (1/HHI)", "desc": "the effective number of comparable players, computed as 1 ÷ HHI. HHI (Herfindahl index) = sum of every rival's squared review share: a high HHI means concentrated (few players own it), a low HHI means scattered/fragmented (many similar-sized players). 1/HHI turns that into 'effective # of equal players' — this is the 'concentrated vs scattered' axis, independent of who's #1.  + = a diverse, no-clear-leader field is GOOD (easy to slip in);  − = a fragmented swarm is BAD (diffuse demand)", "w": 0}]},
 {"id": "winnability", "label": "Right to win today", "desc": "can we win MH here — measured RELATIVE to the local field. How far we out-review the nearby rivals, plus how visible the clinic is on Google. Because it's relative, a clinic where we tower over the rivals (we ~600, them ~180) scores high even if the raw count calls them 'strong' — which is the whole point.", "w": 25, "color": "#7d5ba6", "subs": [
   {"id": "reldom", "label": "How far we lead the field", "desc": "our reviews head-to-head vs the STRONGEST nearby MH rival (≤5km). 50% = tied with the biggest rival; higher = we tower over it. This is the relative read — a Whitefield (we 608 vs their 186 → 77%) lands high here even though Competition counts 2 'strong' rivals.", "w": 45},
   {"id": "rank",  "label": "Beat the local pack",   "desc": "share of nearby MH rivals we out-review (≤5km) — #1 in the pack / beat everyone = 100.", "w": 30},
   {"id": "srch",  "label": "Clinic reach (GMB)", "desc": "our Google listing's searches/wk — clinic-wide reach that will funnel MH patients once launched.", "w": 25}]},
 {"id": "shsafe", "label": "SH stays safe", "desc": "launching MH here shouldn't cannibalise our existing sexual-health business. HIGH = our SH is entrenched (near #1 locally, owns the review base, healthy SH-specific lead flow) so it can look after itself while we add MH. All sub-buckets are SH-specific — no overlap with Right-to-win. SH competition density is a tunable sub-bucket — set its sign yourself.", "w": 20, "color": "#b8862e", "subs": [
   {"id": "shreldom", "label": "How far we lead the SH field", "desc": "our SH reviews head-to-head vs the STRONGEST nearby SH rival (≤5km). 50% = tied with the biggest SH rival; higher = we tower over the field. The relative read — same idea as MH's 'how far we lead', so a clinic we dominate scores high even where the raw count says 'strong rivals'.", "w": 35},
   {"id": "shrank",  "label": "Our SH rank (local)", "desc": "our position in the local SH pack (~#1 = entrenched). Scored so a better rank = higher score.", "w": 20},
   {"id": "shleads", "label": "Our SH leads (SH-tagged)", "desc": "GMB leads tagged to sexual health (cat=SH), last-4-week average — the SH-SPECIFIC funnel, split out from the clinic-wide GMB total so it doesn't overlap Right-to-win.", "w": 15},
   {"id": "shstrong", "label": "SH strong rivals (100+)", "desc": "how many nearby SH rivals clear the bar below — established SH incumbents. −weight by default: more strong SH competition means our SH is more contested. (mirrors MH 'strong-rival count')", "w": -30},
   {"id": "shshare", "label": "Our SH review share (vs whole field)", "adv": True, "desc": "our SH reviews ÷ (ours + ALL nearby SH rivals') within 5km — share vs the whole field (vs 'how far we lead' which is head-to-head vs the single biggest). Defaults to 0.", "w": 0},
   {"id": "shcount",  "label": "SH rival count (pure)", "adv": True, "desc": "how many relevant SH rivals are nearby (≤5km), regardless of size. Direction is YOUR call: −weight = a crowded SH field is riskier to distract from; +weight = a busy SH market validates durable demand. Defaults to 0.", "w": 0},
   {"id": "shdom",    "label": "SH top-rival dominance", "adv": True, "desc": "the #1 SH rival's SHARE of local SH reviews — is one giant dominating the SH field? Tunable: −weight = a dominant SH incumbent nearby is a threat to our SH; +weight = a single beatable giant. Defaults to 0.", "w": 0},
   {"id": "shdiv",    "label": "SH field diversity (1/HHI)", "adv": True, "desc": "effective number of comparable SH players (1 ÷ HHI) — concentrated vs scattered SH field. Tunable sign. Defaults to 0.", "w": 0}]},
]

presets = {
 "Balanced":        {"demand": 25, "competition": -25, "winnability": 25, "shsafe": 20},
 "Winnability-led": {"demand": 20, "competition": -20, "winnability": 45, "shsafe": 15},
 "Protect SH":      {"demand": 20, "competition": -15, "winnability": 20, "shsafe": 45},
}

nT1 = sum(1 for c in clinics if c['tier'] == 'T1'); nT2 = len(clinics) - nT1
D = {"strong": STRONG, "nT1": nT1, "nT2": nT2, "n": len(clinics),
     "groups": groups, "clinics": clinics, "presets": presets}

CSS = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Allo · MH Launch — Scoring Explorer</title><style>
:root{--bg:#f4f6f8;--card:#fff;--ink:#1b2733;--mut:#748092;--line:#e6e9ec;--navy:#1f3a5f;--red:#b8503c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:13.5px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1240px;margin:0 auto;padding:22px 24px}
h1{font-size:22px;margin:0 0 3px}.sub{color:var(--mut);font-size:12.5px;margin-bottom:14px}
.eq{font-size:14px;font-weight:700;color:var(--navy);background:#eaf0f6;border:1px solid #dbe6f1;border-radius:9px;padding:9px 13px;margin-bottom:12px;display:inline-block}
.tierbar{display:flex;gap:8px;margin:0 0 14px;align-items:center}
.tierbar .tl{font-size:11px;color:var(--mut);text-transform:uppercase;font-weight:700;margin-right:2px}
.tierbar button{padding:6px 13px;border:1px solid var(--line);background:#fff;border-radius:20px;font-size:12px;font-weight:600;cursor:pointer;color:var(--ink)}
.tierbar button.on{background:var(--navy);color:#fff;border-color:var(--navy)}
.tierbar select{padding:6px 10px;border:1px solid var(--line);border-radius:20px;font-size:12px;font-weight:600;color:var(--ink);background:#fff;cursor:pointer}
.compbar{display:flex;gap:8px;margin:-4px 0 14px;align-items:center;flex-wrap:wrap}
.compbar .tl{font-size:11px;color:var(--mut);text-transform:uppercase;font-weight:700;margin-right:2px}
.compbar button{padding:5px 11px;border:1px solid var(--line);background:#fff;border-radius:20px;font-size:12px;font-weight:600;cursor:pointer;color:var(--ink)}
.compbar button.on{background:#eef4fb;border-color:#9cc0e6;color:#1f3a5f}
.compbar button:not(.on){opacity:.5;text-decoration:line-through}
.grid{display:grid;grid-template-columns:340px 1fr;gap:20px;align-items:start}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:12px}
.card .gh{display:flex;justify-content:space-between;align-items:baseline}
.card .gl{font-weight:800;font-size:15px}.card .gv{font-weight:800;font-size:17px;font-variant-numeric:tabular-nums}
.card .gd{color:var(--mut);font-size:11.5px;margin:2px 0 8px}
input[type=range]{width:100%;margin:0}
input.wt{-webkit-appearance:none;appearance:none;height:8px;border-radius:5px;outline:none;
  background:linear-gradient(to right,#e57373 0%,#f0b4b4 47%,#cfd6dd 49%,#cfd6dd 51%,#a9d3a9 53%,#4caf50 100%)}
input.wt::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;width:16px;height:16px;border-radius:50%;background:#1f3a5f;border:2px solid #fff;box-shadow:0 0 3px rgba(0,0,0,.45);cursor:pointer}
input.wt::-moz-range-thumb{width:16px;height:16px;border-radius:50%;background:#1f3a5f;border:2px solid #fff;cursor:pointer}
.sv.pos,.gv.pos{color:#2f7d32}.sv.neg,.gv.neg{color:#c0392b}
details{margin-top:9px;border-top:1px dashed var(--line);padding-top:7px}
summary{cursor:pointer;color:var(--navy);font-size:11.5px;font-weight:700;list-style:none}
summary::-webkit-details-marker{display:none}summary:before{content:'▸ ';}
details[open] summary:before{content:'▾ ';}
.subf{margin-top:9px;margin-bottom:9px}
.subf .st{display:flex;justify-content:space-between;font-size:12px}.subf .sl{font-weight:600}.subf .sv{font-weight:700;font-variant-numeric:tabular-nums}
input.gv{width:58px;text-align:right;border:1px solid var(--line);border-radius:6px;padding:2px 5px;background:#fff}
input.sv{width:52px;text-align:right;border:1px solid var(--line);border-radius:6px;padding:1px 4px;background:#fff}
input.gv:focus,input.sv:focus{outline:2px solid #7d5ba6;border-color:#7d5ba6}
.subf .sd{color:var(--mut);font-size:10.5px;margin-bottom:2px}
.thr{background:#f1f7f2;border:1px solid #d8e8da;border-radius:8px;padding:8px 10px;margin-top:8px}
.thr .tt{display:flex;justify-content:space-between;font-size:12px;font-weight:700;color:#2f7d32}
.revbtns{display:flex;gap:6px;margin:5px 0}.revbtns button{padding:5px 9px;font-size:11px;border-radius:6px}.revbtns button.ron{background:#7d5ba6;color:#fff;border-color:#7d5ba6}
.qbox{width:100%;padding:8px 11px;border:1px solid var(--line);border-radius:8px;font-size:13px;margin-bottom:8px;background:#fff}
.btns{display:flex;gap:8px;margin:2px 0 4px;flex-wrap:wrap}
button{padding:7px 12px;border:1px solid var(--line);background:#fff;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;color:var(--ink)}
button.p{background:var(--navy);color:#fff;border-color:var(--navy)}
table{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:9px 12px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap;font-variant-numeric:tabular-nums}
th{font-size:11px;color:var(--mut);font-weight:700;text-transform:uppercase;background:#fafbfc;cursor:pointer}
th.l,td.l{text-align:left}td.clinic{font-weight:700;text-align:left}
tr.row{cursor:pointer}tr.row:hover{background:#f7fafd}
.chip{display:inline-block;padding:0 6px;border-radius:9px;font-size:10px;font-weight:700;color:#fff;margin-left:6px;vertical-align:middle}
.t1{background:#1f3a5f}.t2{background:#8a97a6}.flag{color:var(--red);font-weight:800;margin-left:4px;cursor:help}
.mcell{color:#2c6cae}.ocell{color:#2f7d32}.scell{color:#7d5ba6}.sccell{font-weight:800;color:var(--navy)}
.drill td{padding:0;background:#fbfcfd}.drillbox{padding:10px 16px 15px 30px;text-align:left}
.rtab{border:none}.rtab th,.rtab td{border-bottom:1px solid #eef1f4;padding:5px 12px 5px 0;font-size:12px;background:transparent;cursor:default}
.far{color:var(--red);font-size:10px;font-weight:600}.hd{font-weight:800;color:var(--navy);font-size:11px;margin-bottom:5px;text-transform:uppercase}
.scoremath{background:#f7fafd;border:1px solid #e3eaf2;border-radius:8px;padding:8px 11px;font-size:12.5px;margin-bottom:8px;line-height:1.7}
.note{color:var(--mut);font-size:11px;margin-top:10px;line-height:1.6}
.showall{margin-top:8px}
.bt{width:100%;border-collapse:collapse;font-size:12px;margin-top:2px}.bt th,.bt td{padding:4px 8px;text-align:right;border-bottom:1px solid var(--line)}.bt th.l,.bt td.l{text-align:left;color:var(--mut);text-transform:none;font-weight:600}.bt th{font-size:10px;color:var(--mut);text-transform:uppercase}.bt tr.gap td{font-weight:800;color:var(--navy)}
</style></head><body><div class="wrap">
<h1>Allo · Mental-Health Launch — Scoring Explorer</h1>
<div class="sub">Every clinic scored 0–100 on three things, ranked <b>within the selected tier</b>. Weight them however you believe — the table re-ranks live. Open “how it’s scored” to see and change exactly what goes into each. &nbsp;·&nbsp; <a href="mh-demand.html" style="color:#2c6cae;font-weight:700;text-decoration:none">📊 Keyword demand &amp; search queries →</a> &nbsp;·&nbsp; <a href="mh-practo.html" style="color:#2c6cae;font-weight:700;text-decoration:none">🏥 Practo locality pageviews →</a> &nbsp;·&nbsp; <a href="mh-scoring.html" style="color:#1f3a5f;font-weight:700;text-decoration:none">📖 How scoring works →</a></div>
<div class="eq" id="eq"></div>
<div class="tierbar"><span class="tl">Launch tier</span></div>
<div class="compbar"><span class="tl">Count as competitor</span></div>
<div class="grid">
 <div>
   <div id="cards"></div>
   <div class="btns" id="presets"></div>
   <div id="btpanel"></div>
   <div class="note" id="caveats"></div>
 </div>
 <div>
   <input id="q" class="qbox" placeholder="🔍  Search a clinic by name…" autocomplete="off">
   <table id="tbl"><thead><tr id="hrow"></tr></thead><tbody id="tb"></tbody></table>
   <div class="showall"><button id="showall">Show all ▾</button> <span class="note" id="cnt"></span></div>
 </div>
</div>
"""

JS = r"""
<script>
const G=D.groups;
let W={},SW={};G.forEach(g=>{W[g.id]=g.w;SW[g.id]={};g.subs.forEach(s=>SW[g.id][s.id]=s.w);});
let sortK='score',sortDir=-1,showAll=false,tier='ALL',strongThr=D.strong,query='',cityF='';
const CLASSES=[['psychiatrist','Psychiatrist / Doctor'],['therapy','Therapist / Counsellor'],['hospital','Hospital / Psych hospital'],['clinic','Clinic / Service / Other']];
let active={psychiatrist:true,therapy:true,hospital:true,clinic:true};
function structLabel(c){var s=strongN(c);if(s===0)return['Open field — no established rival','#2a9d8f'];if(s===1)return['One established incumbent','#b8862e'];if(s===2)return['Two established players','#b8862e'];return[s+' established players — crowded','#b8503c'];}
const fmt=n=>n||n===0?Number(n).toLocaleString('en-IN'):'—';

// ---- tier filter ----
const tiers=[['ALL','All '+D.n],['T1','Tier 1 · '+D.nT1],['T2','Tier 2 · '+D.nT2]];
const CITIES=[...new Set(D.clinics.map(c=>c.city))].sort((a,b)=>a.localeCompare(b));
const cityCount={};D.clinics.forEach(c=>cityCount[c.city]=(cityCount[c.city]||0)+1);
document.querySelector('.tierbar').innerHTML='<span class="tl">Launch tier</span>'+tiers.map(t=>`<button data-t="${t[0]}" class="${t[0]==='ALL'?'on':''}">${t[1]}</button>`).join('')
  +'<span class="tl" style="margin-left:10px">or city</span><select id="citysel"><option value="">— all cities —</option>'+CITIES.map(c=>`<option value="${c}">${c} · ${cityCount[c]}</option>`).join('')+'</select>';
document.querySelectorAll('.tierbar button').forEach(b=>b.onclick=()=>{tier=b.dataset.t;cityF='';document.getElementById('citysel').value='';document.querySelectorAll('.tierbar button').forEach(x=>x.classList.toggle('on',x===b));render();});
document.getElementById('citysel').onchange=e=>{cityF=e.target.value;if(cityF)document.querySelectorAll('.tierbar button').forEach(x=>x.classList.remove('on'));else document.querySelector('.tierbar button').classList.add('on');render();};
function pool(){return cityF?D.clinics.filter(c=>c.city===cityF):D.clinics.filter(c=>tier==='ALL'||c.tier===tier);}
// competitor-class chips
document.querySelector('.compbar').innerHTML='<span class="tl">Count as competitor</span>'+CLASSES.map(c=>`<button data-k="${c[0]}" class="on">${c[1]}</button>`).join('');
document.querySelectorAll('.compbar button').forEach(b=>b.onclick=()=>{active[b.dataset.k]=!active[b.dataset.k];b.classList.toggle('on',active[b.dataset.k]);render();});

// ---- competitor category filter: toggle classes on/off, everything recomputes ----
function af(c){return c.field.filter(x=>active[x.k]);}          // in-scope rivals (selected classes only)
function afRev(c){return af(c).map(x=>x.r);}
function afLocal(c){return af(c).filter(x=>x.n);}               // + within the 5km catchment (for right-to-win)
function strongN(c){return afRev(c).filter(r=>r>=strongThr).length;}
function densityN(c){return af(c).length;}
function localN(c){return afLocal(c).length;}
function beatsN(c){return afLocal(c).filter(x=>c.our_rev>x.r).length;}
// RIGHT TO WIN TODAY — two independent views, each weightable:
//  winRank  = our position in the pack: fraction of nearby (≤5km) rivals we outrank. Robust to a single giant,
//             but ties at 1.0 once we beat everyone.
//  winShare = our review MASS: our share of the local (≤5km) review base. Continuous (separates clinics that beat
//             everyone), but a single giant can suppress it. The two disagree exactly when a lone giant is present.
function winRank(c){var n=localN(c);return n>0?beatsN(c)/n:1;}
function winShare(c){var loc=afLocal(c);var t=loc.reduce((s,x)=>s+x.r,0);var d=c.our_rev+t;return d>0?c.our_rev/d:0.5;}
function topLocalRival(c){var loc=afLocal(c).map(x=>x.r);return loc.length?Math.max.apply(null,loc):0;}
// RELATIVE right-to-win: our reviews head-to-head vs the STRONGEST nearby rival. 0.5 = tied; →1 = we tower over the field.
function relDom(c){var t=topLocalRival(c),o=c.our_rev||0;return (o+t)>0?o/(o+t):0.5;}
function hhiN(c){var rv=afRev(c);var t=rv.reduce((s,x)=>s+x,0)||1;return rv.reduce((s,x)=>s+(x/t)*(x/t),0);}
function topShare(c){var rv=afRev(c);var t=rv.reduce((s,x)=>s+x,0)||1;return rv.length?Math.max.apply(null,rv)/t:0;}
// ---- SH competition, computed LIVE from the SH rival review list against the same "strong" bar as MH ----
function shRev(c){return c.sh_rev||[];}
function shCountN(c){return shRev(c).length;}
function shStrongN(c){return shRev(c).filter(r=>r>=strongThr).length;}   // SH rivals over the shared bar
function shTopShare(c){var rv=shRev(c);var t=rv.reduce((s,x)=>s+x,0)||1;return rv.length?Math.max.apply(null,rv)/t:0;}
function shDiv(c){var rv=shRev(c);var t=rv.reduce((s,x)=>s+x,0)||1;var h=rv.reduce((s,x)=>s+(x/t)*(x/t),0);return h>0?1/h:0;}
function shRivTot(c){return shRev(c).reduce((s,x)=>s+x,0);}
function shSharePct(c){var o=c.sh_our||0,t=shRivTot(c);return (o+t)>0?Math.round(100*o/(o+t)):0;}
function shTopRival(c){var rv=shRev(c);return rv.length?Math.max.apply(null,rv):0;}
// RELATIVE right-to-win for SH: our SH reviews head-to-head vs the strongest nearby SH rival (mirrors MH relDom)
function shRelDom(c){var t=shTopRival(c),o=c.sh_our||0;return (o+t)>0?o/(o+t):0.5;}
// plain-language read of the SH situation: our RELATIVE lead × SH competition pressure (objective, weight-independent)
function shVerdict(c){
  // strength read is relative-first (do we out-review the top rival?), share as a booster; pressure = strong-rival count
  var dom=shRelDom(c), share=(c.sh_our||0)/((c.sh_our||0)+shRivTot(c)||1), strong=shStrongN(c);
  var usStrong=(dom>=0.60 || share>=0.45);
  var usMid=(dom>=0.50 || share>=0.25);
  var compHi=strong>=2;
  if(usStrong&&!compHi) return ['Entrenched','#2a9d8f','we own the local SH field and it isn’t crowded — safe to add MH'];
  if(usStrong&&compHi)  return ['Contested','#b8862e','we hold a real share but the SH field is crowded — keep an eye on SH'];
  if(usMid&&!compHi)    return ['Holding','#3a7ca5','moderate SH standing, limited threat — reasonably safe'];
  if(usMid&&compHi)     return ['Contested','#b8862e','moderate SH standing in a crowded field — watch SH if we add MH'];
  if(compHi)            return ['Exposed','#c0392b','weak SH standing in a crowded field — MH could hurt SH'];
  return ['Quiet','#5d6d7e','thin SH presence but few rivals — low stakes either way'];
}

// ---- raw metric per clinic — natural direction (higher = more of that thing); the WEIGHT SIGN decides help/hurt ----
function raw(c,id){switch(id){
  case 'city':  return c.city_sv;
  case 'count': return densityN(c);      // total rivals
  case 'strong':return strongN(c);       // rivals over the bar (bar=0 → all)
  case 'dom':   return topShare(c);        // #1 rival's share of reviews (is there a giant?)
  case 'div':   {var h=hhiN(c);return h>0?1/h:0;}   // effective number of players (1/HHI) — spread, independent of dominance
  case 'srch':  return c.gmb_srch;
  case 'leads': return c.gmb_leads;
  case 'rank':  return winRank(c);        // our position: fraction of nearby rivals we outrank
  case 'share': return winShare(c);        // our share of the local review base (continuous)
  case 'reldom':return relDom(c);          // RELATIVE: our review lead vs the strongest nearby rival
  case 'shreldom':return shRelDom(c);      // RELATIVE: our SH review lead vs the strongest nearby SH rival
  case 'shrank':  return c.sh_rank==null?null:-c.sh_rank;   // SH local rank, inverted so higher = better position
  case 'shshare': return c.sh_share;       // our SH review share locally
  case 'shleads': return c.sh_leads;       // SH-tagged GMB leads/wk
  case 'shstrong':return shStrongN(c);     // # SH rivals over the live bar (−weight → lowers SH-safe)
  case 'shcount': return shCountN(c);      // # SH rivals (pure)
  case 'shdom':   return shTopShare(c);    // top SH rival's review share
  case 'shdiv':   return shDiv(c);}        // effective # of SH players (1/HHI)
  return null;}
// percentile of c on metric id, among the active pool (only clinics with data)
function pct(c,id,pl){const x=raw(c,id);if(x==null)return null;let below=0,eq=0,n=0;
  pl.forEach(k=>{const v=raw(k,id);if(v==null)return;n++;if(v<x)below++;else if(v===x)eq++;});
  return n?(below+0.5*eq)/n*100:50;}
// weighted blend, NEGATIVE-WEIGHT AWARE: a −weight means 'more of this HURTS' → use (100−percentile), |weight|
function gscore(c,g,pl){let tw=0,acc=0;g.subs.forEach(s=>{const w=SW[g.id][s.id];if(!w)return;const p=pct(c,s.id,pl);if(p==null)return;const aw=Math.abs(w);tw+=aw;acc+=aw*(w>=0?p:100-p);});return tw?acc/tw:50;}
function overall(c,pl){let tw=0,acc=0;G.forEach(g=>{const w=W[g.id];if(!w)return;const gs=gscore(c,g,pl);const aw=Math.abs(w);tw+=aw;acc+=aw*(w>=0?gs:100-gs);});return tw?acc/tw:50;}

// ---- group cards + sub-sliders ----
function subCard(g,s){return `<div class="subf"><div class="st"><span class="sl">${s.label}</span><input class="sv" type="number" min="-100" max="100" step="5" id="sv_${g.id}_${s.id}" value="${s.w}" title="type a weight −100…100"></div><div class="sd">${s.desc}</div><input type="range" class="wt" min="-100" max="100" step="5" value="${s.w}" id="ss_${g.id}_${s.id}"></div>`
  +((g.id==='competition'&&s.id==='strong')?`<div class="thr"><div class="tt"><span>“Strong rival” bar</span><span id="thrv">${strongThr}+ reviews</span></div><input type="range" min="0" max="500" step="25" value="${strongThr}" id="thr"><div class="sd">A rival with this many Google reviews counts as strong. <b>Set to 0</b> to count every rival (pure count). Shared with the SH factor.</div></div>`:'')
  +((g.id==='shsafe'&&s.id==='shstrong')?`<div class="thr"><div class="tt"><span>“Strong rival” bar</span><span id="thrv2">${strongThr}+ reviews</span></div><input type="range" min="0" max="500" step="25" value="${strongThr}" id="thr2"><div class="sd">Same bar as MH Competition — a SH rival with this many reviews counts as strong. Drag either; they stay in sync.</div></div>`:'');}
document.getElementById('cards').innerHTML=G.map(g=>`<div class="card">
  <div class="gh"><span class="gl" style="color:${g.color}">${g.label}</span><input class="gv" type="number" min="-100" max="100" step="5" id="gv_${g.id}" value="${g.w}" title="type a weight −100…100"></div>
  <div class="gd">${g.desc}</div>
  <input type="range" class="wt" min="-100" max="100" step="5" value="${g.w}" id="gs_${g.id}">
  <details><summary>how it’s scored</summary><div>
    ${g.subs.length>1
      ? g.subs.filter(s=>!s.adv).map(s=>subCard(g,s)).join('')
          + (g.subs.some(s=>s.adv)?`<details style="margin:4px 0 0"><summary style="font-size:11px;cursor:pointer;color:var(--mut)">advanced sub-weights (${g.subs.filter(s=>s.adv).length}) — off by default</summary><div style="margin-top:4px">${g.subs.filter(s=>s.adv).map(s=>subCard(g,s)).join('')}</div></details>`:'')
      : `<div class="sd" style="margin-top:2px;line-height:1.6">This factor is a single measure at 100% weight — nothing to sub-weight. It's scored as: <b>${g.subs[0].desc}</b></div>`}
  </div></details>
</div>`).join('');
function clampW(v){v=Math.round((+v||0)/5)*5;return Math.max(-100,Math.min(100,v));}
G.forEach(g=>{
  var gs=document.getElementById('gs_'+g.id), gv=document.getElementById('gv_'+g.id);
  // slider drag → set weight + sync the number box
  gs.addEventListener('input',e=>{W[g.id]=clampW(e.target.value);gv.value=W[g.id];render();});
  // type in the number box → set weight + sync the slider (don't rewrite the box mid-type)
  gv.addEventListener('input',e=>{W[g.id]=clampW(e.target.value);gs.value=W[g.id];render();});
  gv.addEventListener('change',e=>{W[g.id]=clampW(e.target.value);gs.value=gv.value=W[g.id];render();});
  g.subs.forEach(s=>{
    var ss=document.getElementById('ss_'+g.id+'_'+s.id), sv=document.getElementById('sv_'+g.id+'_'+s.id);
    if(!ss||!sv)return;
    ss.addEventListener('input',e=>{SW[g.id][s.id]=clampW(e.target.value);sv.value=SW[g.id][s.id];render();});
    sv.addEventListener('input',e=>{SW[g.id][s.id]=clampW(e.target.value);ss.value=SW[g.id][s.id];render();});
    sv.addEventListener('change',e=>{SW[g.id][s.id]=clampW(e.target.value);ss.value=sv.value=SW[g.id][s.id];render();});
  });
});
function setThr(v){strongThr=+v;['thr','thr2'].forEach(id=>{var el=document.getElementById(id);if(el)el.value=strongThr;});['thrv','thrv2'].forEach(id=>{var el=document.getElementById(id);if(el)el.textContent=strongThr+'+ reviews';});render();}
['thr','thr2'].forEach(id=>{var el=document.getElementById(id);if(el)el.addEventListener('input',e=>setThr(e.target.value));});
document.getElementById('q').addEventListener('input',e=>{query=e.target.value.trim().toLowerCase();render();});

function applyPreset(P){G.forEach(g=>{W[g.id]=P[g.id];document.getElementById('gs_'+g.id).value=P[g.id];document.getElementById('gv_'+g.id).value=P[g.id];});render();}
document.getElementById('presets').innerHTML=Object.keys(D.presets).map((k,i)=>`<button class="${i==0?'p':''}" data-p="${k}">${k}</button>`).join('');
document.querySelectorAll('#presets button').forEach(b=>b.onclick=()=>applyPreset(D.presets[b.dataset.p]));

document.getElementById('caveats').innerHTML='<b>How to read it:</b> Every factor is a 0–100 <i>percentile within the selected tier</i> — switch tiers and a clinic is re-ranked against its own peers. Four factors, cleanly separated: <b style="color:#2c6cae">Demand</b> (search volume, no competition in it) · <b style="color:#2f7d32">Competition</b> (the only place rivals count — pure count, strong-rival count, and concentration: top-rival dominance + field diversity/HHI) · <b style="color:#7d5ba6">Right to win today</b> (our MH-specific standing — rank in the local MH pack + share of local MH reviews — plus clinic-wide GMB discovery, the one shared reach signal, which lives here only) · <b style="color:#b8862e">SH stays safe</b> (is our sexual-health business entrenched enough — SH rank, SH review share, SH-tagged leads — that adding MH won’t cannibalise it; SH density is a tunable ± sub-bucket). <b>No signal is double-counted:</b> GMB leads are split by vertical (SH-tagged leads feed SH-safe; MH leads are ~0 pre-launch), and clinic-wide discovery sits in Right-to-win only. <b>Weights can be negative</b> — a −weight means “more of this HURTS the score”, so you set whether competition, concentration, etc. help or hurt (no reverse toggle needed). Open any clinic to see its <b>Score math</b>. Winnability is partly an <i>outcome</i> (strong clinics accumulate reviews) — read it as standing, not destiny. <span style="color:var(--red)">⚡</span> = crowded.';
document.getElementById('showall').onclick=()=>{showAll=!showAll;render();};
document.getElementById('hrow').innerHTML='<th class="l" data-k="loc">Clinic</th>'+G.map(g=>`<th data-k="${g.id}" style="color:${g.color}">${g.label}</th>`).join('')+'<th data-k="score">Score</th>';
document.querySelectorAll('#tbl thead th').forEach(th=>th.onclick=()=>{const k=th.dataset.k;sortDir=(sortK===k)?-sortDir:(k==='loc'?1:-1);sortK=k;render();});

function render(){
  const pl=pool();
  const wabs=G.reduce((a,g)=>a+Math.abs(W[g.id]),0);
  document.getElementById('eq').innerHTML='Score = '+G.filter(g=>W[g.id]).map(g=>`${g.label} ×${W[g.id]<0?'−':''}${Math.abs(W[g.id])} <span style="color:var(--mut)">(${wabs?Math.round(100*Math.abs(W[g.id])/wabs):0}%)</span>`).join('  +  ');
  let arr=pl.map(c=>{const gs={};G.forEach(g=>gs[g.id]=Math.round(gscore(c,g,pl)));return {c,gs,score:Math.round(overall(c,pl))};});
  arr.sort((a,b)=>{let A=(sortK==='score')?a.score:(sortK==='loc'?a.c.loc:a.gs[sortK]);let B=(sortK==='score')?b.score:(sortK==='loc'?b.c.loc:b.gs[sortK]);if(typeof A==='string')return A.localeCompare(B)*sortDir;return (A-B)*sortDir;});
  if(query)arr=arr.filter(x=>(x.c.loc+' '+x.c.city).toLowerCase().includes(query));
  const show=(showAll||query)?arr:arr.slice(0,10);
  const tb=document.getElementById('tb');tb.innerHTML='';
  show.forEach(x=>{const c=x.c;const crowded=strongN(c)>=2||c.giant;
    const tr=document.createElement('tr');tr.className='row';
    tr.innerHTML=`<td class="clinic">${c.loc}<span class="chip ${c.tier==='T1'?'t1':'t2'}">${c.tier}</span>${crowded?'<span class="flag" title="crowded: ≥2 strong rivals or a giant">⚡</span>':''}<div style="font-size:10.5px;color:var(--mut);font-weight:400">${c.city}</div></td>`
      +G.map(g=>`<td style="color:${g.color};font-weight:600">${x.gs[g.id]}</td>`).join('')+`<td class="sccell">${x.score}</td>`;
    tr.onclick=()=>toggle(c,tr);tb.appendChild(tr);
  });
  document.getElementById('showall').style.display=query?'none':'inline-block';
  document.getElementById('showall').textContent=showAll?'Show top 10 only ▴':('Show all '+arr.length+' ▾');
  document.getElementById('cnt').textContent=query?(arr.length+' match'+(arr.length===1?'':'es')):(showAll?arr.length+' clinics':'top 10 of '+arr.length);
}
function toggle(c,tr){
  if(tr.nextSibling&&tr.nextSibling.className==='drill'){tr.nextSibling.remove();return;}
  document.querySelectorAll('.drill').forEach(d=>d.remove());
  const dr=document.createElement('tr');dr.className='drill';
  var mhAllo={name:'Allo Health — '+c.loc, type:'Our clinic', reviews:c.our_rev||0, rating:null, km:0, near:true, maps:c.our_maps, allo:true, k:null};
  var mhList=c.rivals.map(x=>Object.assign({},x,{allo:false})).concat([mhAllo]).sort((a,b)=>(b.reviews||0)-(a.reviews||0));
  const rv=mhList.map(x=>{
    if(x.allo){return `<tr style="background:#eaf2fb"><td class="l"><b>${x.maps?`<a href="${x.maps}" target="_blank" style="color:#1f3a5f;text-decoration:none;border-bottom:1px dotted #9cc0e6">${x.name}</a>`:`<span style="color:#1f3a5f">${x.name}</span>`}</b> <span style="font-size:9px;color:#fff;background:#1f3a5f;font-weight:700;padding:1px 6px;border-radius:8px">US</span></td><td class="l">${x.type}</td><td><b style="color:#1f3a5f">${fmt(x.reviews)}</b></td><td>${x.rating?x.rating+'★':'—'}</td><td>—</td></tr>`;}
    var off=!active[x.k];return `<tr style="${off?'opacity:.35':''}"><td class="l"><b>${x.maps?`<a href="${x.maps}" target="_blank" style="color:var(--ink);text-decoration:none;border-bottom:1px dotted #9cc0e6">${x.name}</a>`:x.name}</b>${off?' <span style="font-size:9.5px;color:var(--red);font-weight:700">excluded</span>':''}</td><td class="l">${x.type}</td><td>${fmt(x.reviews)}${(!off&&x.reviews>=strongThr)?' <span style="color:#2f7d32;font-weight:700">strong</span>':''}</td><td>${x.rating||'—'}★</td><td>${x.km!=null?x.km+'km'+(x.near?'':' <span class="far">&gt;5km</span>'):'<span class="far">dist?</span>'}</td></tr>`}).join('');
  dr.innerHTML=`<td colspan="5"><div class="drillbox">
    <div class="hd">Local MH competition — ${c.loc} · ${c.city} (${c.tier})</div>
    ${(function(){
      var pl=pool();var sl=structLabel(c);var afr=afRev(c).slice().sort((a,b)=>b-a);
      var eff=(hhiN(c)>0?1/hhiN(c):0).toFixed(1);
      function sc(id){var g=G.find(x=>x.id===id);return g?Math.round(gscore(c,g,pl)):'—';}
      function blk(color,label,note,score,detail){return `<div style="border-left:3px solid ${color};padding:4px 10px;background:#fbfcfd;border-radius:5px;margin-bottom:4px;font-size:11.5px;line-height:1.55"><b style="color:${color};font-size:12.5px">${label}</b> <b style="color:${color};font-size:13.5px">${score}</b> <span style="color:var(--mut);font-size:10px">${note}</span> <span style="color:#555"> · ${detail}</span></div>`;}
      var out='';
      out+=blk('#2c6cae','Demand','how much local search there is',sc('demand'),`City search demand <b>${fmt(c.city_sv)}/mo</b>${c.pzone?` <span style="color:var(--mut)">· Practo locality ref: ${c.pzone} ${fmt(c.pzone_pv)} pageviews (not scored)</span>`:''}${c.verify_demand?' · <span style="color:var(--red)">verify demand</span>':''}`);
      out+=blk('#2f7d32','Competition','how contested the field is',sc('competition'),`<b style="color:${sl[1]}">${sl[0]}</b> · <b>${densityN(c)}</b> rivals · <b>${strongN(c)}</b> over ${strongThr}+ reviews · top rival owns <b>${Math.round(topShare(c)*100)}%</b> (dominance) · ~<b>${eff}</b> effective players (diversity) · biggest rivals ${afr.slice(0,3).map(fmt).join(' · ')||'—'} reviews`);
      out+=blk('#7d5ba6','Right to win today','how far we lead the local MH field',sc('winnability'),`we lead <b>${Math.round(relDom(c)*100)}%</b> head-to-head vs top rival <span style="color:var(--mut)">(our <b>${fmt(c.our_rev)}</b> vs <b>${fmt(topLocalRival(c))}</b>)</span> · out-review <b>${beatsN(c)} of ${localN(c)}</b> nearby · clinic reach <b>${fmt(c.gmb_srch)}</b>/wk`);
      var v=shVerdict(c), shOur=c.sh_our||0, shRT=shRivTot(c), spct=shSharePct(c);
      out+=`<div style="border-left:3px solid #b8862e;padding:6px 10px;background:#fbfcfd;border-radius:5px;margin-bottom:4px">
        <div style="display:flex;justify-content:space-between;align-items:baseline">
          <span><b style="color:#b8862e;font-size:12.5px">SH stays safe</b> <b style="color:#b8862e;font-size:13.5px">${sc('shsafe')}</b>
            <span style="font-size:9.5px;color:#fff;background:${v[1]};font-weight:700;padding:1px 8px;border-radius:9px;margin-left:5px;letter-spacing:.03em">${v[0].toUpperCase()}</span></span>
        </div>
        <div style="font-size:10.5px;color:var(--mut);margin:2px 0 6px">${v[2]}</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;font-size:11px;margin-bottom:6px">
          <div style="flex:1;min-width:180px;border-left:2px solid #b8862e;padding-left:8px"><span style="color:#96701f;font-weight:700">Where we stand</span><br>lead <b>${Math.round(shRelDom(c)*100)}%</b> head-to-head vs top rival <span style="color:var(--mut)">(our <b>${fmt(c.sh_our)}</b> vs <b>${fmt(shTopRival(c))}</b>)</span> · SH rank <b>~#${c.sh_rank!=null?c.sh_rank:'?'}</b> · <b>${fmt(c.sh_leads)}</b> leads/wk</div>
          <div style="flex:1;min-width:180px;border-left:2px solid #c0392b;padding-left:8px"><span style="color:#c0392b;font-weight:700">SH competition</span><br><b>${shCountN(c)}</b> rivals · <b>${shStrongN(c)}</b> strong (${strongThr}+) · top owns <b>${Math.round(shTopShare(c)*100)}%</b></div>
        </div>
        <div style="display:flex;height:15px;border-radius:3px;overflow:hidden;border:1px solid var(--line)">
          <div style="width:${spct}%;background:#b8862e;min-width:${spct>0?'2px':'0'}"></div><div style="flex:1;background:#e6e9ec"></div></div>
        <div style="font-size:9.5px;color:var(--mut);margin-top:2px">Who owns the local SH review base — <b style="color:#96701f">us ${fmt(shOur)} (${spct}%)</b> vs SH rivals ${fmt(shRT)}</div>
      </div>`;
      var shAllo={name:'Allo Health — '+c.loc, reviews:c.sh_our||0, rating:null, km:0, near:true, maps:c.sh_maps, allo:true};
      var shList=(c.sh_rivals||[]).map(x=>Object.assign({},x,{allo:false})).concat([shAllo]).sort((a,b)=>(b.reviews||0)-(a.reviews||0));
      var shrv=shList.map(x=>{
        if(x.allo){return `<tr style="background:#fdf3e0"><td class="l"><b>${x.maps?`<a href="${x.maps}" target="_blank" style="color:#96701f;text-decoration:none;border-bottom:1px dotted #dcc089">${x.name}</a>`:`<span style="color:#96701f">${x.name}</span>`}</b> <span style="font-size:9px;color:#fff;background:#b8862e;font-weight:700;padding:1px 6px;border-radius:8px">US</span></td><td><b style="color:#96701f">${fmt(x.reviews)}</b></td><td>${x.rating?x.rating+'★':'—'}</td><td>—</td></tr>`;}
        return `<tr><td class="l"><b>${x.maps?`<a href="${x.maps}" target="_blank" style="color:var(--ink);text-decoration:none;border-bottom:1px dotted #9cc0e6">${x.name}</a>`:x.name}</b></td><td>${fmt(x.reviews)}${x.reviews>=strongThr?' <span style="color:#2f7d32;font-weight:700">strong</span>':''}</td><td>${x.rating||'—'}★</td><td>${x.km!=null?x.km+'km'+(x.near?'':' <span class="far">&gt;5km</span>'):'<span class="far">dist?</span>'}</td></tr>`;
      }).join('');
      out+=`<details style="margin:1px 0 6px 10px"><summary style="cursor:pointer;font-size:11px;color:#b8862e;font-weight:700;padding:2px 0">▸ SH competitors &amp; where Allo stands (${shList.length})</summary><table class="rtab" style="margin-top:4px"><thead><tr><th class="l">SH rival</th><th>Reviews</th><th>Rating</th><th>Dist</th></tr></thead><tbody>${shrv}</tbody></table></details>`;
      return `<div style="margin-bottom:8px">${out}</div>`;
    })()}
    ${(function(){var pl=pool();var wabs=G.reduce((a,g)=>a+Math.abs(W[g.id]),0)||1;
      var parts=G.filter(g=>W[g.id]).map(g=>{var gs=Math.round(gscore(c,g,pl));var wp=Math.round(100*Math.abs(W[g.id])/wabs);var rw=(W[g.id]<0?'−':'')+Math.abs(W[g.id]);return `<span style="color:${g.color};font-weight:700">${g.label} ${gs}</span> ×${rw} <span style="color:var(--mut);font-weight:400">(${wp}%)</span>`;}).join('  +  ');
      var subrows=G.map(g=>{var ws=g.subs.filter(s=>SW[g.id][s.id]);if(!ws.length)return '';var inner=ws.map(s=>{var p=Math.round(pct(c,s.id,pl));var w=SW[g.id][s.id];return `${s.label} <b>${p}</b>${w<0?' <span style="color:#c0392b">(−)</span>':''} ×${w>0?'+':''}${w}`;}).join(' · ');return `<div style="font-size:11px;color:var(--mut);margin-top:3px"><b style="color:${g.color}">${g.label} = ${Math.round(gscore(c,g,pl))}</b> &nbsp;←&nbsp; ${inner}</div>`;}).join('');
      return `<div class="scoremath">Score math: ${parts} &nbsp;=&nbsp; <b>${Math.round(overall(c,pl))}</b> &nbsp;<span style="color:var(--mut);font-weight:400">(×your slider weight; the % is that weight as a share of all weights — they're relative, so only the ratio matters. Each factor is a 0–100 percentile within ${cityF?cityF:(tier==='ALL'?'all clinics':tier)}.)</span><details style="margin-top:5px;border:none;padding:0"><summary style="font-size:11px">show sub-score split</summary>${subrows}</details></div>`;})()}
    <table class="rtab"><thead><tr><th class="l">Rival</th><th class="l">Type</th><th>Reviews</th><th>Rating</th><th>Dist</th></tr></thead><tbody>${rv}</tbody></table>
  </div></td>`;
  tr.after(dr);
}
render();
</script></body></html>
"""

html = CSS + "<script>const D=" + json.dumps(D) + ";</script>" + JS
open(OUT, 'w').write(html)
print('wrote', OUT, '·', len(clinics), 'clinics ·', nT1, 'T1 /', nT2, 'T2 · bytes', len(html))
