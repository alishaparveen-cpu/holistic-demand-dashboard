#!/usr/bin/env python3
"""
build_clinic_data.py — Generate data_clinic.json with per-clinic and per-city
availability-indexed demand analysis, using the same methodology as the
demand-diagnostics weekly_demand_review.py script.

Methodology:
  Q1: Availability from roster_slots (doctor-active days per clinic per week)
  Q2: Actual bookings from appointments (distinct patients per day, summed)
  Q3: Lead attribution fields (utm_source, utm_medium, origin, patient phone)
  Q4: Clinic phone numbers (for Exotel-originated GMB attribution)

  Practo attribution: patient phone matched against Practo sheet (phone matching,
  NOT utm_source — which is why Practo is undercounted in build_data.py).

  Expected bookings formula (same as demand-diagnostics):
    avg_wd_rate = sum(bk on active weekdays) / sum(active weekday count) — prior 8 wks
    avg_we_rate = sum(bk on active weekend days) / sum(active weekend count) — prior 8 wks
    expected    = avg_wd_rate × this_week_wda + avg_we_rate × this_week_wea
    gap%        = (actual / expected − 1) × 100
    drop        = gap% < −10%

Classification:
  Drop Both Week   — W5 gap% < −10% AND W6 gap% < −10%
  Drop this week   — W5 okay, W6 < −10%
  Recovering       — W5 dropped, W6 recovering
  Okay             — both ≥ −10%
  Insufficient     — fewer than 4 valid prior weeks

Usage:
    cd /Users/alishaparveen/holistic-demand-dashboard
    AWS_PROFILE=allo-data python3 scripts/build_clinic_data.py

    Optional args:
      --w6-start  YYYY-MM-DD   (default: last complete Monday)
      --output    PATH          (default: data_clinic.json)

Output: data_clinic.json consumed by the dashboard's availability index and
        a new per-clinic demand review card.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta

import boto3

# ── Constants ──────────────────────────────────────────────────────────────────
CLUSTER    = 'warehouse'
DATABASE   = 'allo_prod'
DB_USER    = 'redshift_admin'
AWS_REGION = os.environ.get('AWS_REGION', 'ap-south-1')

EXCLUDED_LOCS = "('c7d8c9d2-f389-4e8f-a260-71110195b83f','ffe8d849-3099-48fe-a2df-e324c4befe56')"

PRIOR_WINDOW_WEEKS = 8
MIN_VALID_PRIOR_WEEKS = 4
MIN_WD_ACTIVE  = 2
MIN_WE_ACTIVE  = 1
DROP_THRESHOLD = -10  # gap% below this = drop

SOURCE_ORDER = ['gmb', 'google', 'organic', 'fb', 'practo', 'directwalkin', 'other']
SOURCE_NAMES = {
    'gmb': 'GMB', 'google': 'Google', 'organic': 'Organic', 'fb': 'FB/Meta',
    'practo': 'Practo', 'directwalkin': 'Walk-in', 'other': 'Other',
}

# Practo sheet (column J = Patient_Phone_Number, format: 91XXXXXXXXXX or 919XXXXXXXXX)
PRACTO_SHEET_ID  = '1pTPQgdSUaomRuj_49dARVJ4Vtiy34uE73X4gqqkwlaE'
PRACTO_SHEET_TAB = 'Practo'

# Special Exotel numbers → known channel
SPECIAL_PHONE_NUMBERS = {
    '08046800927': 'organic',
    '08046801869': 'fb',
    '08046810621': 'fb',
    '08047491172': 'clinicspots',
}


# ── Redshift helpers ───────────────────────────────────────────────────────────
def get_client():
    return boto3.client('redshift-data', region_name=AWS_REGION)


def run_query(client, sql: str) -> list[list]:
    """Execute SQL via Redshift Data API and return rows as list of lists."""
    resp = client.execute_statement(
        ClusterIdentifier=CLUSTER, Database=DATABASE, DbUser=DB_USER, Sql=sql,
    )
    qid = resp['Id']
    print(f'    submitted {qid[:8]}...', end='', flush=True)
    for _ in range(180):
        time.sleep(5)
        desc = client.describe_statement(Id=qid)
        if desc['Status'] == 'FINISHED':
            print(f' done ({desc.get("Duration", 0)//1_000_000_000}s)')
            break
        if desc['Status'] in ('FAILED', 'ABORTED'):
            raise RuntimeError(f"Query failed: {desc.get('Error', '')}")
    else:
        raise RuntimeError('Query timed out after 15 minutes')

    rows = []
    result = client.get_statement_result(Id=qid)
    while True:
        for r in result['Records']:
            rows.append([list(f.values())[0] if f else None for f in r])
        if 'NextToken' not in result:
            break
        result = client.get_statement_result(Id=qid, NextToken=result['NextToken'])
    return rows


# ── Practo phone loader ────────────────────────────────────────────────────────
def load_practo_phones_from_sheet() -> set[str]:
    """
    Download Practo sheet from Google Sheets and extract patient phone numbers.
    Sheet has Patient_Phone_Number column (index 9) in format 91XXXXXXXXXX (12 digits)
    or 919XXXXXXXXX. Converts all to +91XXXXXXXXXX format for matching.
    """
    url = f'https://docs.google.com/spreadsheets/d/{PRACTO_SHEET_ID}/export?format=csv&sheet={PRACTO_SHEET_TAB}'
    phones: set[str] = set()
    print(f'  Downloading Practo sheet from Google Sheets...', end='', flush=True)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f'\n  WARNING: Could not fetch Practo sheet: {e}')
        print('  Practo phone matching disabled.')
        return phones

    reader = csv.reader(io.StringIO(raw))
    phone_col = None
    for row_i, row in enumerate(reader):
        if row_i == 0:
            # Find the Patient_Phone_Number column
            for ci, h in enumerate(row):
                if 'phone' in h.lower() and 'patient' in h.lower():
                    phone_col = ci
                    break
            if phone_col is None:
                # Default to column 9 based on observed sheet structure
                phone_col = 9
            continue
        if not row or len(row) <= phone_col:
            continue
        raw_phone = str(row[phone_col]).strip()
        if not raw_phone:
            continue
        # Normalise to +91XXXXXXXXXX
        # Formats seen: 919XXXXXXXXX (12 digits), 91XXXXXXXXX (11 digits?), 10 digit
        digits = ''.join(c for c in raw_phone if c.isdigit())
        if len(digits) == 12 and digits.startswith('91'):
            phones.add(f'+{digits}')       # +919XXXXXXXXX
        elif len(digits) == 11 and digits.startswith('91'):
            phones.add(f'+{digits}')       # +91XXXXXXXXXX (11 digit country form)
        elif len(digits) == 10:
            phones.add(f'+91{digits}')     # pure 10-digit
        # else skip

    print(f' done — {len(phones):,} Practo phones loaded')
    return phones


# ── Clinic phone set ───────────────────────────────────────────────────────────
def build_clinic_phone_set(location_rows: list[list]) -> set[str]:
    phones: set[str] = set()
    for row in location_rows:
        phone = str(row[1]).strip() if row[1] and row[1] is not True else ''
        if not phone:
            continue
        if phone.startswith('+91'):
            phones.add('0' + phone[3:])
        phones.add(phone)
    return phones


# ── Source attribution ─────────────────────────────────────────────────────────
def attribute_source(utm_source, utm_medium, origin, clinic_phones,
                     patient_phone=None, practo_phones=None) -> str:
    # Priority 0: Practo phone match
    if practo_phones and patient_phone:
        ps = str(patient_phone).strip() if patient_phone and patient_phone is not True else ''
        if ps and ps in practo_phones:
            return 'practo'

    us  = str(utm_source).strip().lower() if utm_source and utm_source is not True else ''
    um  = str(utm_medium).strip().lower() if utm_medium and utm_medium is not True else ''
    umr = str(utm_medium).strip()          if utm_medium and utm_medium is not True else ''
    org = str(origin).strip().lower()      if origin     and origin     is not True else ''

    # WhatsApp
    if um == 'whatsapp':
        return 'gmb_whatsapp' if us == 'gmb' else ('whatsapp_organic' if us in ('', 'organic') else f'whatsapp_{us}')

    # Exotel inbound
    if org == 'exotel':
        if umr in SPECIAL_PHONE_NUMBERS:
            return SPECIAL_PHONE_NUMBERS[umr]
        if umr in clinic_phones:
            return 'gmb'
        return us if us else 'unknown'

    if us:
        return us
    if org:
        return org
    return 'unknown'


def bucket_source(ch: str) -> str:
    if ch in ('gmb', 'gmb_whatsapp'):            return 'gmb'
    if ch == 'google':                            return 'google'
    if ch in ('organic', 'whatsapp_organic'):     return 'organic'
    if ch == 'fb':                                return 'fb'
    if ch == 'practo':                            return 'practo'
    if ch == 'directwalkin':                      return 'directwalkin'
    if ch == 'clinicspots':                       return 'other'
    return 'other'


# ── Safe type helpers ──────────────────────────────────────────────────────────
def si(v) -> int:
    if v is None or isinstance(v, bool): return 0
    try: return int(v)
    except: return 0

def sf(v):
    if v is None or isinstance(v, bool): return None
    try: return float(v)
    except: return None

def ss(v) -> str:
    if v is None or isinstance(v, bool): return ''
    return str(v)


# ── SQL queries ────────────────────────────────────────────────────────────────
def q1_availability(ds: str, de: str) -> str:
    return f"""
WITH da AS (
    SELECT l.city, l.locality AS clinic, l.id AS lid,
        DATE(rs.start_time + INTERVAL '5.5 hours') AS dt,
        EXTRACT(DOW FROM (rs.start_time + INTERVAL '5.5 hours')) AS dow,
        ROUND(SUM(EXTRACT(EPOCH FROM (rs.end_time - rs.start_time)) / 60.0), 1) AS sc
    FROM allo_consultations.roster_slots rs
        JOIN allo_consultations.types t ON t.id = rs.type_id
        JOIN allo_health.locations l ON rs.location_id = l.id
    WHERE l.deleted_at IS NULL AND t.name = 'Screening Call'
        AND rs.is_realized = 1 AND rs.overlaps_non_bookable_block = 0
        AND ((rs.is_booked = 1 AND rs.overlaps_other_booked_type = 0)
             OR (rs.available_for_booking = 1 AND rs.in_repeat_boundary = 0))
        AND l.id NOT IN {EXCLUDED_LOCS}
        AND DATE(rs.start_time + INTERVAL '5.5 hours') BETWEEN '{ds}' AND '{de}'
    GROUP BY l.city, l.locality, l.id, dt, dow
),
db AS (
    SELECT l.id AS lid, DATE(a.start_time + INTERVAL '5.5 hours') AS dt,
        COUNT(DISTINCT c.patient_id) AS bk
    FROM allo_consultations.appointments a
        JOIN allo_consultations.consultations c ON a.consultation_id = c.id
        JOIN allo_health.locations l ON a.location_id = l.id
    WHERE a.deleted_at IS NULL AND c.deleted_at IS NULL AND l.deleted_at IS NULL
        AND c.consultation_type_id = (SELECT id FROM allo_consultations.types WHERE name = 'Screening Call')
        AND l.id NOT IN {EXCLUDED_LOCS}
        AND DATE(a.start_time + INTERVAL '5.5 hours') BETWEEN '{ds}' AND '{de}'
    GROUP BY l.id, dt
),
dc AS (
    SELECT da.city, da.clinic, da.lid, da.dt, da.dow, da.sc,
        CASE WHEN da.sc >= 60 THEN 1 ELSE 0 END AS act,
        CASE WHEN da.dow IN (1,2,3,4,5) THEN 1 ELSE 0 END AS wd,
        CASE WHEN da.dow IN (0,6) THEN 1 ELSE 0 END AS we,
        COALESCE(db.bk, 0) AS bk
    FROM da LEFT JOIN db ON da.lid = db.lid AND da.dt = db.dt
)
SELECT city, clinic, DATE_TRUNC('week', dt) AS wst,
    SUM(CASE WHEN wd=1 AND act=1 THEN 1 ELSE 0 END) AS wda,
    SUM(CASE WHEN we=1 AND act=1 THEN 1 ELSE 0 END) AS wea,
    CASE WHEN SUM(CASE WHEN wd=1 AND act=1 THEN 1 ELSE 0 END) >= {MIN_WD_ACTIVE}
        THEN ROUND(CAST(SUM(CASE WHEN wd=1 AND act=1 THEN bk ELSE 0 END) AS FLOAT)
            / SUM(CASE WHEN wd=1 AND act=1 THEN 1 ELSE 0 END), 2) ELSE NULL END AS wd_rate,
    CASE WHEN SUM(CASE WHEN we=1 AND act=1 THEN 1 ELSE 0 END) >= {MIN_WE_ACTIVE}
        THEN ROUND(CAST(SUM(CASE WHEN we=1 AND act=1 THEN bk ELSE 0 END) AS FLOAT)
            / SUM(CASE WHEN we=1 AND act=1 THEN 1 ELSE 0 END), 2) ELSE NULL END AS we_rate
FROM dc
GROUP BY city, clinic, DATE_TRUNC('week', dt)
ORDER BY city, clinic, wst
""".strip()


def q2_actuals(ds: str, de: str) -> str:
    return f"""
SELECT city, clinic, wst, SUM(daily_bk) AS bk FROM (
    SELECT l.city, l.locality AS clinic,
        DATE_TRUNC('week', DATE(a.start_time + INTERVAL '5.5 hours')) AS wst,
        DATE(a.start_time + INTERVAL '5.5 hours') AS dt,
        COUNT(DISTINCT c.patient_id) AS daily_bk
    FROM allo_consultations.appointments a
        JOIN allo_consultations.consultations c ON a.consultation_id = c.id
        JOIN allo_health.locations l ON a.location_id = l.id
    WHERE a.deleted_at IS NULL AND c.deleted_at IS NULL AND l.deleted_at IS NULL
        AND c.consultation_type_id = (SELECT id FROM allo_consultations.types WHERE name = 'Screening Call')
        AND l.id NOT IN {EXCLUDED_LOCS}
        AND DATE(a.start_time + INTERVAL '5.5 hours') BETWEEN '{ds}' AND '{de}'
    GROUP BY l.city, l.locality, wst, dt
)
GROUP BY city, clinic, wst
ORDER BY city, clinic, wst
""".strip()


def q3_lead_attrs(ds: str, de: str) -> str:
    return f"""
SELECT l.locality,
    ld.utm_source, ld.utm_medium, ld.origin,
    DATE_TRUNC('week', DATE(a.start_time + INTERVAL '5.5 hours')) AS wst,
    c.patient_id, p.phone_no
FROM allo_consultations.appointments a
    JOIN allo_consultations.consultations c ON a.consultation_id = c.id
    JOIN allo_health.locations l ON a.location_id = l.id
    JOIN allo_persons.patient p ON c.patient_id = p.id
    LEFT JOIN allo_persons.lead ld ON p.lead_id = ld.id
WHERE a.deleted_at IS NULL AND c.deleted_at IS NULL AND l.deleted_at IS NULL
    AND c.consultation_type_id = (SELECT id FROM allo_consultations.types WHERE name = 'Screening Call')
    AND l.id NOT IN {EXCLUDED_LOCS}
    AND DATE(a.start_time + INTERVAL '5.5 hours') BETWEEN '{ds}' AND '{de}'
""".strip()


def q4_clinic_phones() -> str:
    return "SELECT locality, phone_no FROM allo_health.locations WHERE deleted_at IS NULL AND phone_no IS NOT NULL AND phone_no != ''"


# ── Classification ─────────────────────────────────────────────────────────────
CAT_ORDER = {'Drop Both Week': 0, 'Drop this week': 1, 'Recovering': 2, 'Okay': 3, 'Insufficient Data': 4}


def classify(w5_gap: float | None, w6_gap: float | None, has_bm: bool) -> str:
    if not has_bm:
        return 'Insufficient Data'
    if w5_gap is not None and w6_gap is not None:
        if w5_gap < DROP_THRESHOLD and w6_gap < DROP_THRESHOLD:
            return 'Drop Both Week'
        if w5_gap >= DROP_THRESHOLD and w6_gap < DROP_THRESHOLD:
            return 'Drop this week'
        if w5_gap < DROP_THRESHOLD and w6_gap >= DROP_THRESHOLD:
            return 'Recovering'
        return 'Okay'
    if w6_gap is not None and w6_gap < DROP_THRESHOLD:
        return 'Drop this week'
    return 'Okay'


def generate_remark(cat: str, sources: dict, w5d: dict, w6d: dict, n_valid: int) -> str:
    if cat == 'Insufficient Data':
        return f'Only {n_valid} valid prior weeks (need {MIN_VALID_PRIOR_WEEKS}).'
    if cat == 'Okay':
        return ''

    persistent, w6only = [], []
    for ch in ['gmb', 'google', 'organic', 'fb', 'practo', 'directwalkin']:
        if ch not in sources:
            continue
        d   = sources[ch]
        avg = d['avg']
        if avg == 0:
            continue
        name = SOURCE_NAMES.get(ch, ch)
        a2   = avg * 2
        combined_pct = (d['w5'] + d['w6'] - a2) / a2 * 100
        w6_pct       = (d['w6'] - avg) / avg * 100
        if combined_pct <= -20:
            persistent.append(f"{name} {combined_pct:+.0f}%")
        elif w6_pct <= -20:
            w6only.append(f"{name} W6:{w6_pct:+.0f}%")

    all_drops = persistent + w6only
    if not all_drops:
        return ''
    if len(all_drops) >= 4:
        return f"ALL channels declining: {', '.join(all_drops)}. Location-level issue."
    worsening = (w6d.get('gap_pct') is not None and w5d.get('gap_pct') is not None
                 and w6d['gap_pct'] < w5d['gap_pct'])
    trend = 'Worsening.' if worsening else ''
    return f"Key drops: {', '.join(all_drops)}. {trend}".strip()


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='Build data_clinic.json from Redshift')
    parser.add_argument('--w6-start', default=None,
                        help='W6 Monday YYYY-MM-DD (default: last complete Monday)')
    parser.add_argument('--output', default=None,
                        help='Output JSON path (default: data_clinic.json next to this script\'s parent)')
    args = parser.parse_args()

    # ── Week date calculation ──────────────────────────────────────────────────
    if args.w6_start:
        w6_dt = datetime.strptime(args.w6_start, '%Y-%m-%d')
    else:
        today   = datetime.now().date()
        dow     = today.weekday()               # 0=Mon
        cur_mon = datetime.combine(today - timedelta(days=dow), datetime.min.time())
        w6_dt   = cur_mon - timedelta(weeks=1)  # last complete week

    w5_dt      = w6_dt - timedelta(weeks=1)
    prior_start = w5_dt - timedelta(weeks=PRIOR_WINDOW_WEEKS)
    prior_weeks = [(prior_start + timedelta(weeks=i)).strftime('%Y-%m-%d')
                   for i in range(PRIOR_WINDOW_WEEKS)]
    w5_week = w5_dt.strftime('%Y-%m-%d')
    w6_week = w6_dt.strftime('%Y-%m-%d')
    ds      = prior_start.strftime('%Y-%m-%d')
    de      = (w6_dt + timedelta(days=6)).strftime('%Y-%m-%d')

    out_path = args.output or str(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data_clinic.json')
    )

    print('=' * 60)
    print('  Allo Health — Clinic Demand Data Builder')
    print('=' * 60)
    print(f'  W5 : {w5_week}  (prior week)')
    print(f'  W6 : {w6_week}  (current week)')
    print(f'  Prior benchmark: {prior_weeks[0]} → {prior_weeks[-1]} ({PRIOR_WINDOW_WEEKS} weeks)')
    print(f'  Query range    : {ds} → {de}')
    print(f'  Output         : {out_path}')
    print()

    # ── Step 1: Practo phones ──────────────────────────────────────────────────
    print('[1/5] Loading Practo patient phones from Google Sheet...')
    practo_phones = load_practo_phones_from_sheet()

    # ── Step 2–5: Redshift queries ─────────────────────────────────────────────
    client = get_client()

    print('\n[2/5] Q1 — Availability (roster_slots, active doctor-days + booking rate)...')
    r1 = run_query(client, q1_availability(ds, de))
    print(f'       → {len(r1):,} clinic-week rows')

    print('\n[3/5] Q2 — Actual bookings (appointments, distinct patients per day)...')
    r2 = run_query(client, q2_actuals(ds, de))
    print(f'       → {len(r2):,} clinic-week rows')

    print('\n[4/5] Q3 — Lead attribution (utm + patient phone for Practo matching)...')
    r3 = run_query(client, q3_lead_attrs(ds, de))
    print(f'       → {len(r3):,} booking rows')

    print('\n[5/5] Q4 — Clinic phone numbers (Exotel → GMB attribution)...')
    r4 = run_query(client, q4_clinic_phones())
    clinic_phones = build_clinic_phone_set(r4)
    print(f'       → {len(clinic_phones):,} phone variants')

    # ── Process Q1: availability per (city, clinic, week) ─────────────────────
    print('\nProcessing...')
    avail: dict = defaultdict(dict)  # (city, clinic) → week → {wda, wea, wd_rate, we_rate}
    for r in r1:
        city   = ss(r[0]) or '?'
        clinic = ss(r[1]) or '?'
        wst    = ss(r[2])[:10]
        avail[(city, clinic)][wst] = {
            'wda': si(r[3]), 'wea': si(r[4]),
            'wd_rate': sf(r[5]), 'we_rate': sf(r[6]),
        }

    # ── Process Q2: actual bookings per (city, clinic, week) ──────────────────
    actuals: dict = defaultdict(dict)  # (city, clinic) → week → count
    for r in r2:
        city   = ss(r[0]) or '?'
        clinic = ss(r[1]) or '?'
        wst    = ss(r[2])[:10]
        actuals[(city, clinic)][wst] = si(r[3])

    # ── Process Q3: source attribution ────────────────────────────────────────
    # clinic → bucket → week → set[patient_id]  (deduplicated)
    src: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    for r in r3:
        clinic    = ss(r[0]) or '?'
        wst       = ss(r[4])[:10]
        patient_id = r[5]
        patient_ph = r[6] if len(r) > 6 else None
        ch = attribute_source(r[1], r[2], r[3], clinic_phones,
                              patient_phone=patient_ph, practo_phones=practo_phones)
        src[clinic][bucket_source(ch)][wst].add(str(patient_id))

    # Convert sets → counts
    src_counts: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for clinic in src:
        for bkt in src[clinic]:
            for wst in src[clinic][bkt]:
                src_counts[clinic][bkt][wst] = len(src[clinic][bkt][wst])

    # ── Build per-clinic records ───────────────────────────────────────────────
    all_clinics = []
    for (city, clinic), aw in avail.items():
        # Valid prior weeks: must have wd_rate and wda >= MIN_WD_ACTIVE
        pwd = [aw[w]['wd_rate'] for w in prior_weeks
               if w in aw and aw[w]['wd_rate'] is not None and aw[w]['wda'] >= MIN_WD_ACTIVE]
        pwe = [aw[w]['we_rate'] for w in prior_weeks
               if w in aw and aw[w]['we_rate'] is not None and aw[w]['wea'] >= MIN_WE_ACTIVE]

        has_bm = len(pwd) >= MIN_VALID_PRIOR_WEEKS
        avg_wd = sum(pwd) / len(pwd) if pwd else None
        avg_we = sum(pwe) / len(pwe) if pwe else None

        cur: dict = {}
        for lbl, wk in [('w5', w5_week), ('w6', w6_week)]:
            if wk not in aw:
                continue
            av  = aw[wk]
            act = actuals.get((city, clinic), {}).get(wk, 0)
            if avg_wd is not None and has_bm:
                exp = avg_wd * av['wda'] + (avg_we * av['wea'] if avg_we else 0.0)
                gap     = act - exp
                gap_pct = round(gap / exp * 100, 1) if exp > 0 else None
            else:
                exp = gap = gap_pct = None
            cur[lbl] = {
                'wda': av['wda'], 'wea': av['wea'], 'act': act,
                'exp': round(exp, 1) if exp is not None else None,
                'gap': round(gap, 1) if gap is not None else None,
                'gap_pct': gap_pct,
            }

        if not cur:
            continue

        w5d = cur.get('w5', {}); w6d = cur.get('w6', {})
        w5p = w5d.get('gap_pct');  w6p = w6d.get('gap_pct')
        cat = classify(w5p, w6p, has_bm)

        # Source breakdown for this clinic
        sources: dict = {}
        csrc = src_counts[clinic]
        for bkt in SOURCE_ORDER:
            cw   = csrc.get(bkt, {})
            pv   = [cw.get(w, 0) for w in prior_weeks]
            cavg = sum(pv) / len(pv) if pv else 0.0
            w5v  = cw.get(w5_week, 0)
            w6v  = cw.get(w6_week, 0)
            if cavg < 0.5 and w5v == 0 and w6v == 0:
                continue
            sources[bkt] = {'avg': round(cavg, 1), 'w5': w5v, 'w6': w6v}

        # ── Availability-indexed expected per source ────────────────────────
        # source_exp_indexed = source_share × clinic_availability_indexed_expected
        # source_share = source_avg / sum(all_source_avgs)   (historical mix)
        # This is more accurate than raw avg when clinic avail changes week-to-week.
        total_src_avg = sum(s['avg'] for s in sources.values())
        for bkt in sources:
            share = sources[bkt]['avg'] / total_src_avg if total_src_avg > 0 else 0.0
            sources[bkt]['exp_w5'] = (
                round(share * w5d['exp'], 1) if w5d.get('exp') is not None else None
            )
            sources[bkt]['exp_w6'] = (
                round(share * w6d['exp'], 1) if w6d.get('exp') is not None else None
            )

        remark = generate_remark(cat, sources, w5d, w6d, len(pwd))

        all_clinics.append({
            'clinic': clinic, 'city': city, 'cat': cat,
            'n_valid': len(pwd),
            'avg_wd': round(avg_wd, 2) if avg_wd is not None else None,
            'avg_we': round(avg_we, 2) if avg_we is not None else None,
            'w5': w5d, 'w6': w6d,
            'sources': sources, 'remark': remark,
            'w5p': w5p, 'w6p': w6p,
            'combined': (w5p or 0) + (w6p or 0),
        })

    # Sort: worst first within each category
    all_clinics.sort(key=lambda c: (
        CAT_ORDER.get(c['cat'], 9),
        c['combined'] if c['cat'] == 'Drop Both Week' else (c['w6p'] or 0),
    ))

    # ── Roll up to city level ──────────────────────────────────────────────────
    city_map: dict = defaultdict(lambda: {
        'clinics': [], 'w5_act': 0, 'w5_exp': 0.0, 'w6_act': 0, 'w6_exp': 0.0,
        'src_w5': defaultdict(int), 'src_w6': defaultdict(int), 'src_avg': defaultdict(float), 'src_cnt': defaultdict(int),
    })
    for c in all_clinics:
        cm = city_map[c['city']]
        cm['clinics'].append(c['clinic'])
        if c['w5']:
            cm['w5_act'] += c['w5'].get('act', 0)
            cm['w5_exp'] += c['w5'].get('exp') or 0
        if c['w6']:
            cm['w6_act'] += c['w6'].get('act', 0)
            cm['w6_exp'] += c['w6'].get('exp') or 0
        for bkt, sv in c['sources'].items():
            cm['src_w5'][bkt]    += sv['w5']
            cm['src_w6'][bkt]    += sv['w6']
            cm['src_avg'][bkt]   += sv['avg']
            cm['src_cnt'][bkt]   += 1
            cm.setdefault('src_exp_w5', defaultdict(float))[bkt] += sv.get('exp_w5') or 0
            cm.setdefault('src_exp_w6', defaultdict(float))[bkt] += sv.get('exp_w6') or 0

    all_cities = []
    for city, cm in city_map.items():
        w5_gap = round((cm['w5_act'] / cm['w5_exp'] - 1) * 100, 1) if cm['w5_exp'] > 0 else None
        w6_gap = round((cm['w6_act'] / cm['w6_exp'] - 1) * 100, 1) if cm['w6_exp'] > 0 else None
        # City cat = worst of constituent clinics with data
        city_clinics = [c for c in all_clinics if c['city'] == city]
        worst_cat = min(city_clinics, key=lambda c: CAT_ORDER.get(c['cat'], 9))['cat'] if city_clinics else 'Insufficient Data'

        sources = {}
        for bkt in SOURCE_ORDER:
            if bkt not in cm['src_avg']:
                continue
            cnt = cm['src_cnt'][bkt]
            sources[bkt] = {
                'avg':    round(cm['src_avg'][bkt], 1),
                'w5':     cm['src_w5'][bkt],
                'w6':     cm['src_w6'][bkt],
                'exp_w5': round(cm.get('src_exp_w5', {}).get(bkt, 0), 1),
                'exp_w6': round(cm.get('src_exp_w6', {}).get(bkt, 0), 1),
            }

        all_cities.append({
            'city': city,
            'cat': worst_cat,
            'n_clinics': len(cm['clinics']),
            'clinics': sorted(cm['clinics']),
            'w5': {'act': cm['w5_act'], 'exp': round(cm['w5_exp'], 1), 'gap_pct': w5_gap},
            'w6': {'act': cm['w6_act'], 'exp': round(cm['w6_exp'], 1), 'gap_pct': w6_gap},
            'sources': sources,
        })

    all_cities.sort(key=lambda x: (CAT_ORDER.get(x['cat'], 9), x['w6']['gap_pct'] or 0))

    # ── Print summary ──────────────────────────────────────────────────────────
    from collections import Counter
    cats = Counter(c['cat'] for c in all_clinics)
    print(f'\n{"="*60}')
    print(f'  CLINIC SUMMARY  (W5={w5_week}, W6={w6_week})')
    print(f'{"="*60}')
    print(f'  Total clinics: {len(all_clinics)}')
    for cat in ['Drop Both Week', 'Drop this week', 'Recovering', 'Okay', 'Insufficient Data']:
        n = cats.get(cat, 0)
        if n:
            print(f'    {cat}: {n}')

    # Drop Both Week list
    both = [c for c in all_clinics if c['cat'] == 'Drop Both Week']
    if both:
        print(f'\n  Drop Both Week ({len(both)} clinics):')
        for c in both[:15]:
            w5s = f"W5 {c['w5p']:+.1f}%" if c['w5p'] is not None else 'W5 —'
            w6s = f"W6 {c['w6p']:+.1f}%" if c['w6p'] is not None else 'W6 —'
            exp6 = c['w6'].get('exp')
            act6 = c['w6'].get('act')
            print(f'    {c["city"]} — {c["clinic"]:30s} {w5s}  {w6s}  (exp {exp6} / act {act6})')

    # New drops this week
    new_drops = [c for c in all_clinics if c['cat'] == 'Drop this week']
    if new_drops:
        print(f'\n  Drop this week ({len(new_drops)} clinics):')
        for c in new_drops[:10]:
            w6s = f"{c['w6p']:+.1f}%" if c['w6p'] is not None else '—'
            print(f'    {c["city"]} — {c["clinic"]:30s}  W6 {w6s}')

    # Source-wise drops for Drop Both Week
    print(f'\n  Source-wise drops (Drop Both Week clinics):')
    src_drops: dict = defaultdict(list)
    for c in both:
        for bkt, sv in c['sources'].items():
            avg = sv['avg']
            if avg < 1:
                continue
            w6_pct = (sv['w6'] - avg) / avg * 100
            if w6_pct <= -20:
                exp_n = round(avg); act_n = sv['w6']
                src_drops[bkt].append(f"{c['city']}/{c['clinic']} W6:{w6_pct:+.0f}% (exp:{exp_n} act:{act_n})")

    for bkt in SOURCE_ORDER:
        drops = src_drops.get(bkt, [])
        if drops:
            print(f'\n  {SOURCE_NAMES[bkt]}:')
            for d in drops[:8]:
                print(f'    {d}')

    # ── Write output ───────────────────────────────────────────────────────────
    output = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'w5': w5_week,
        'w6': w6_week,
        'prior_weeks': prior_weeks,
        'drop_threshold': DROP_THRESHOLD,
        'min_valid_prior_weeks': MIN_VALID_PRIOR_WEEKS,
        'practo_phones_loaded': len(practo_phones),
        'source_order': SOURCE_ORDER,
        'source_names': SOURCE_NAMES,
        'clinics': all_clinics,
        'cities': all_cities,
    }

    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f'\n✅ Written {len(all_clinics)} clinics, {len(all_cities)} cities → {out_path}')
    print(f'   Practo phones matched from: {len(practo_phones):,} records')


if __name__ == '__main__':
    main()
