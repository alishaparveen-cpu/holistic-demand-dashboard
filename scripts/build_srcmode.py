#!/usr/bin/env python3
"""Build data_srcmode.json — SC bookings broken out by SOURCE × VIA-MEDIUM (call/web/whatsapp/book/walkin),
per clinic × week. This is the *joint* the two margin-cubes don't store.

TAXONOMY (leaf set per source):
  GMB        → call · whatsapp · web
  Google Ads → call · web
  Practo     → call · book
  Meta       → call · web · whatsapp
  Organic    → call · web · whatsapp
  Walk-in    → walkin
  Other      → (flat, no split)

TWO PATHS — the script picks automatically:
  • REAL (needs Redshift/VPN): matches each booked patient's phone to the actual Exotel number they dialed
    (per-clinic GMB number, shared Google/Practo/FB/Organic numbers) for the call source; falls to lead.origin
    /user_flow for web/whatsapp; Practo-CRM origin → book; no-lead → walkin. Writes TRUE leaf counts.
  • PROVISIONAL (offline, default when SSO down): takes each source's REAL weekly booking subtotal from
    data_booking_source.json and splits it across that source's allowed modes using the clinic's global
    call:web:whatsapp margin (data_contact_mode.json) — restricted to the allowed modes. Leaves flagged est.
    Subtotals are real; only the within-source split is an estimate until the pull.

Run: python3 scripts/build_srcmode.py            (auto: real if VPN up, else provisional)
     python3 scripts/build_srcmode.py --clinic "Bangalore|Indiranagar"
"""
import os, sys, json, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- canonical source → allowed via-modes -------------------------------------------------
TAXONOMY = {
    'GMB':        ['call', 'whatsapp', 'web'],
    'Google Ads': ['call', 'web'],
    'Practo':     ['call', 'book'],
    'Meta':       ['call', 'web', 'whatsapp'],
    'Organic':    ['call', 'web', 'whatsapp'],
    'Walk-in':    ['walkin'],
}
# data_booking_source channel-name  →  taxonomy source
SRC_MAP = {'Google Maps (GMB)': 'GMB', 'Google Ads': 'Google Ads', 'Practo': 'Practo',
           'Meta': 'Meta', 'Organic': 'Organic', 'Walk-in': 'Walk-in'}
OTHER = 'Other'   # everything unmapped (No tag / AI-Social / Referral / JustDial / untracked) folds here, flat
# contact_mode label → leaf mode
MODE_MAP = {'Call': 'call', 'Website': 'web', 'WhatsApp': 'whatsapp', 'Practo': 'book', 'Walk-in/Ops': 'walkin'}


def largest_remainder(total, weights):
    """Split integer `total` across buckets ∝ weights, exact-sum, largest-remainder rounding."""
    keys = list(weights.keys()); W = sum(weights.values())
    if total <= 0 or W <= 0:
        return {k: 0 for k in keys}
    raw = {k: total * weights[k] / W for k in keys}
    fl = {k: int(raw[k]) for k in keys}
    rem = total - sum(fl.values())
    for k in sorted(keys, key=lambda k: raw[k] - fl[k], reverse=True)[:rem]:
        fl[k] += 1
    return fl


def sso_up():
    try:
        p = subprocess.run(['aws', 'sts', 'get-caller-identity'], env={**os.environ, 'AWS_PROFILE': 'redshift-data'},
                           capture_output=True, text=True, timeout=12)
        return p.returncode == 0
    except Exception:
        return False


def build_provisional():
    bs = json.load(open(os.path.join(ROOT, 'data_booking_source.json')))
    cm = json.load(open(os.path.join(ROOT, 'data_contact_mode.json')))['by_clinic']
    weeks = bs['_meta']['weeks']; N = len(weeks)
    out = {'_meta': {'weeks': weeks, 'taxonomy': TAXONOMY, 'provisional': True,
                     'source': 'PROVISIONAL split — real per-source subtotals (data_booking_source) × global '
                               'mode margin (data_contact_mode), restricted to allowed modes. Leaves flagged est. '
                               'Overwritten by the real phone→Exotel join once VPN is up.'}}
    clinics = [k for k in bs.keys() if k != '_meta']
    for cl in clinics:
        chan = bs[cl].get('channel', {})
        # clinic global mode margin (call/web/whatsapp) from contact_mode
        marg = {'call': 0, 'web': 0, 'whatsapp': 0}
        for wk, d in (cm.get(cl) or {}).items():
            if isinstance(d, dict):
                for lab, v in d.items():
                    m = MODE_MAP.get(lab)
                    if m in marg and isinstance(v, (int, float)):
                        marg[m] += v
        if sum(marg.values()) == 0:
            marg = {'call': 1, 'web': 1, 'whatsapp': 1}   # avoid div0 → even split
        node = {}
        for srcname, src in SRC_MAP.items():
            if srcname not in chan:
                continue
            tot = chan[srcname].get('total') or [0] * N
            allowed = TAXONOMY[src]
            leaves = {m: [0] * N for m in allowed}
            for i in range(N):
                if src == 'Walk-in':
                    leaves['walkin'][i] = tot[i] or 0
                elif src == 'Practo':
                    # Practo is booking-platform dominated; calls rare — default to book (flagged est)
                    leaves['book'][i] = tot[i] or 0
                    leaves['call'][i] = 0
                else:
                    w = {m: marg.get(m, 0) for m in allowed}
                    sp = largest_remainder(tot[i] or 0, w)
                    for m in allowed:
                        leaves[m][i] = sp[m]
            node[src] = {**{m: leaves[m] for m in allowed}, '_total': [tot[i] or 0 for i in range(N)],
                         '_est': src != 'Walk-in'}
        # Other (flat, no split)
        oth = [0] * N
        for srcname, src in chan.items():
            if srcname in SRC_MAP:
                continue
            t = src.get('total') or [0] * N
            oth = [oth[i] + (t[i] or 0) for i in range(N)]
        if sum(oth):
            node[OTHER] = {'_total': oth, '_flat': True}
        out[cl] = node
    return out


def build_not_booked(out):
    """Add out[clinic]['_not_booked'] — leads that did NOT book, from the demand tracker (reconciles:
    leads − booked on the same base). Taxonomy: Practo (flat) · GMB (call·web) · Google (ai_intent).
    Group totals (Practo, GMB+Google) are REAL; the GMB-vs-Google split and GMB call/web are provisional."""
    try:
        df = json.load(open(os.path.join(ROOT, 'data_demand_funnel.json')))
    except Exception:
        return
    wk = df['_meta']['weeks']; N = len(wk)
    # per-clinic GMB-vs-Google + GMB call/web priors (from attribution where available; else defaults)
    PRIOR = {'Bangalore|Indiranagar': {'google_share': 42 / (175 + 42), 'gmb_call': 175 / (175 + 44)}}
    DEF = {'google_share': 0.18, 'gmb_call': 0.80}
    def w(a):  # skip idx0 (partial), take next 8 wks
        return [ (a or [0]*N)[i] or 0 for i in range(1, min(9, N)) ]
    weeks8 = wk[1:9]
    for cl, node in list(out.items()):
        if cl == '_meta' or cl not in df:
            continue
        v = df[cl]; pr = PRIOR.get(cl, DEF)
        def nb(group):  # not-booked weekly = leads − booked, clamped ≥0
            L = w(v[group]['leads']); B = w(v[group]['booked'])
            return [max(0, L[i] - B[i]) for i in range(len(L))]
        practo_nb = nb('practo')
        gg_nb = nb('gmb_google')
        goog = [round(x * pr['google_share']) for x in gg_nb]
        gmb = [gg_nb[i] - goog[i] for i in range(len(gg_nb))]
        gmb_call = [round(x * pr['gmb_call']) for x in gmb]
        gmb_web = [gmb[i] - gmb_call[i] for i in range(len(gmb))]
        node['_not_booked'] = {
            '_weeks': weeks8,
            'Practo': {'_total': practo_nb, '_flat': True},
            'GMB': {'call': gmb_call, 'web': gmb_web, '_total': gmb, '_est': True},
            'Google': {'ai_intent': goog, '_total': goog, '_est': True,
                       '_note': 'Google leads surfaced via AI-intent classification (relevant flag)'},
        }


def main():
    clinic = None
    if '--clinic' in sys.argv:
        clinic = sys.argv[sys.argv.index('--clinic') + 1]
    real = sso_up()
    if real:
        print('SSO up — REAL path not yet wired into this builder; using build_real() TODO. '
              'Falling back to provisional for now.', file=sys.stderr)
        # (Real per-patient join lives in probe_indiranagar_srcmode.py; fold in once verified.)
    out = build_provisional()
    build_not_booked(out)
    OUTP = os.path.join(ROOT, 'data_srcmode.json')
    json.dump(out, open(OUTP, 'w'), separators=(',', ':'))
    print(f"wrote {OUTP} · {len([k for k in out if k!='_meta'])} clinics · mode={'REAL' if real else 'PROVISIONAL'}")
    # pretty-print the requested clinic's tree
    show = clinic or 'Bangalore|Indiranagar'
    if show in out:
        wk = out['_meta']['weeks']; n8 = min(8, len(wk))
        print(f"\n=== {show} · SC bookings by SOURCE × VIA-MEDIUM · last {n8} wks "
              f"({wk[n8-1]} … {wk[0]}){'  [PROVISIONAL split]' if not real else ''} ===")
        node = out[show]
        order = ['GMB', 'Google Ads', 'Practo', 'Meta', 'Organic', 'Walk-in', OTHER]
        for src in order:
            if src not in node:
                continue
            nd = node[src]
            st = sum((nd['_total'])[:n8])
            tag = ' ·est' if nd.get('_est') else (' ·flat' if nd.get('_flat') else '')
            print(f"  {src:12} {st:5}{tag}")
            for m in TAXONOMY.get(src, []):
                if m in nd:
                    print(f"      ↳ {m:10} {sum(nd[m][:n8]):5}")


if __name__ == '__main__':
    main()
