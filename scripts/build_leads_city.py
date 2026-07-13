#!/usr/bin/env python3
"""data_leads_city.json — attributable leads at CITY level (ALL web included, misattribution washes out).
Every lead is attributed to a city by priority:
  1. Practo location-code -> city   2. AI user_city (calls, is_our_city)
  3. source_url city (web landing page /sexual-health/<city>)   4. GMB number -> city
Channel (GMB/Google Ads/Practo/Organic/Other) + medium (call/web/book/whatsapp) + number/url/intent/category/booked,
same as the clinic funnel but city-scoped. Booked = phone ever booked an SC at any clinic in that city.
Run: AWS_PROFILE=redshift-data python3 scripts/build_leads_city.py
"""
import os, sys, json, subprocess, datetime
from collections import defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, 'scripts', 'redshift_query.py')
WEEKS = ['2026-07-06','2026-06-29','2026-06-22','2026-06-15','2026-06-08','2026-06-01','2026-05-25','2026-05-18',
         '2026-05-11','2026-05-04','2026-04-27','2026-04-20','2026-04-13','2026-04-06','2026-03-30',
         '2026-03-23','2026-03-16','2026-03-09','2026-03-02','2026-02-23','2026-02-16','2026-02-09',
         '2026-02-02','2026-01-26','2026-01-19','2026-01-12']   # weekly axis (26 wks, aligned with bookings cube — ends 6–12 Jul)
WI = {w: i for i, w in enumerate(WEEKS)}; N = len(WEEKS)
# daily axis: recent 8 weeks INCLUDING the current (partial) week 2026-07-06 — powers the day-of-week / week-to-date comparison.
# Kept separate from WEEKS so the weekly axis stays aligned with the bookings cube; current-week leads land only in d[].
DAY_WEEKS = ['2026-07-06','2026-06-29','2026-06-22','2026-06-15','2026-06-08','2026-06-01','2026-05-25','2026-05-18']
DAYS = []
for _wkm in reversed(DAY_WEEKS):
    _d0 = datetime.date.fromisoformat(_wkm)
    DAYS += [(_d0 + datetime.timedelta(days=_k)).isoformat() for _k in range(7)]
DI = {d: i for i, d in enumerate(DAYS)}; ND = len(DAYS)
def wk_monday(dstr):
    d = datetime.date.fromisoformat(dstr)
    return (d - datetime.timedelta(days=d.weekday())).isoformat()
CHANNELS = ['GMB', 'Google Ads', 'Meta', 'Practo', 'Organic', 'Other']

# number -> canonical city (from the GMB map) ; and URL/AI token -> canonical city
GMAP = json.load(open(os.path.join(ROOT, 'data_gmb_number_clinic.json')))
NUM_CITY = {num: clinic.split('|')[0] for num, clinic in GMAP.items() if '|' in clinic}
NUM_LOC = {num: clinic.split('|')[1] for num, clinic in GMAP.items() if '|' in clinic}   # number -> clinic locality
CANON = sorted({c for c in NUM_CITY.values()})
# token (lowercase, hyphenated) -> canonical, plus common URL aliases
CITYMAP = {}
for c in CANON:
    CITYMAP[c.lower()] = c
    CITYMAP[c.lower().replace(' ', '-')] = c
CITYMAP.update({'bengaluru': 'Bangalore', 'mysore': 'Mysuru', 'mangalore': 'Mangaluru',
                'vizag': 'Visakhapatnam', 'vishakhapatnam': 'Visakhapatnam'})

# --- attribution recovery maps (Q4/Q5): read the clinic/city already sitting in campaign & locality ---
import re as _re
def _norm(s): return _re.sub(r'[^a-z0-9]', '', (s or '').lower())
_clinics = [v.split('|', 1) for v in set(GMAP.values()) if '|' in v]
_city_n = {}
for _c, _l in _clinics:
    _city_n[_c] = _city_n.get(_c, 0) + 1
# GMB clinic-gmb campaign slug -> (city, locality). Locality slug always; bare-city slug only for single-clinic cities.
GMB_SLUG = {}
for _c, _l in _clinics:
    GMB_SLUG[_norm(_l)] = (_c, _l)
    if _city_n[_c] == 1:
        GMB_SLUG.setdefault(_norm(_c), (_c, _l))
GMB_SLUG.update({'krishnarajapuram': ('Bangalore', 'KR Puram'), 'falnir': ('Mangaluru', 'Falnir Rd')})
# Google t1/t2 campaign city token -> canonical city
TOK_CITY = {_norm(c): c for c in CANON}
TOK_CITY.update({'vizag': 'Visakhapatnam', 'navi': 'Navi Mumbai', 'hubballi': 'Hubli', 'blr': 'Bangalore',
                 'vadodara': 'Vadodara', 'gandhinagar': 'Gandhinagar'})
# clinic locality -> its city (backfill city when a call gives a locality but no confirmed city)
LOC2CITY = {_l: _c for _c, _l in _clinics}

def values(pairs, c1, c2):
    return ' UNION ALL '.join(f"SELECT '{a}' AS {c1}, '{b}' AS {c2}" for a, b in pairs)
def gmbvalues():   # number -> (city, locality)
    return ' UNION ALL '.join(f"SELECT '{n}' AS num, '{NUM_CITY[n]}' AS city, '{NUM_LOC[n]}' AS locality" for n in NUM_CITY)

SQL = """
WITH gmbnum AS (
    {GMBNUM}
),
citymap AS (
    {CITYMAP}
),
gmbslug AS (   -- GMB '<clinic>-clinic-gmb' campaign slug -> (city, locality)
    {GMBSLUG}
),
tokcity AS (   -- Google 't1/t2_<city>_...' campaign token -> city
    {TOKCITY}
),
loccity AS (   -- clinic locality -> its city (backfill)
    {LOCCITY}
),
loc AS (   -- Practo location code -> canonical city + clinic locality
  SELECT l.code, COALESCE(cm.city, INITCAP(l.city)) AS city, l.locality AS locality
  FROM allo_health.locations l LEFT JOIN citymap cm ON cm.tok = LOWER(l.city)
  WHERE l.deleted_at IS NULL AND l.code IS NOT NULL AND l.code <> ''
),
call_ai AS (   -- phone -> most-recent inbound call's AI city / clinic locality / intent / intent-strength / category
  SELECT ph, city, locality, intent, strength, cat FROM (
    SELECT RIGHT(ec."from",10) AS ph,
      CASE WHEN ca.analysis.user_intent.user_city.is_our_city = true
           THEN COALESCE(cm.city, INITCAP(ca.analysis.user_intent.user_city.best_match::varchar)) END AS city,
      CASE WHEN ca.analysis.user_intent.locality_mentioned.is_our_locality = true
           THEN ca.analysis.user_intent.locality_mentioned.best_match::varchar END AS locality,
      ca.analysis.user_intent.result::varchar AS intent,
      ca.analysis.patient_intent_strength.result::varchar AS strength,
      ca.analysis.diagnoses.category::varchar AS cat,
      ROW_NUMBER() OVER (PARTITION BY RIGHT(ec."from",10) ORDER BY ec.start_time DESC) rn
    FROM allo_analytics.call_analyses ca
    JOIN allo_vendors.exotel_calls ec ON ec.call_id=ca.call_id AND ec.routed_to='lead_to_call' AND ec.direction='inbound'
    LEFT JOIN citymap cm ON cm.tok = LOWER(ca.analysis.user_intent.user_city.best_match::varchar)
    WHERE ec.start_time >= '2025-11-01'
  ) q WHERE rn=1
),
lead_attr AS (
  SELECT l.id, RIGHT(REGEXP_REPLACE(COALESCE(l.phone_no,''),'[^0-9]',''),10) AS ph,
    TO_CHAR(DATE_TRUNC('week', l.created_at + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
    DATE(l.created_at + INTERVAL '5.5 hours') AS created,
    -- CITY priority: Practo code > GMB clinic-gmb slug > AI user_city > source_url city > GMB number city > Google campaign token > locality backfill
    COALESCE(
      CASE WHEN LOWER(COALESCE(l.utm_source,''))='practo' THEN plc.city END,
      gs.city,
      cai.city,
      ucm.city,
      gn.city,
      tc.city,
      lcb.city
    ) AS city,
    COALESCE(   -- clinic locality where we CAN pin it (else NULL -> stays city-level)
      CASE WHEN LOWER(COALESCE(l.utm_source,''))='practo' THEN plc.locality END,
      gs.locality,
      gn.locality,
      cai.locality
    ) AS locality,
    CASE
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('gmb','googlelisting','google listing','google_listing') THEN 'GMB'
      WHEN LOWER(COALESCE(l.utm_source,''))='practo' THEN 'Practo'
      WHEN (l.gclid IS NOT NULL AND l.gclid<>'')
           OR (LOWER(COALESCE(l.utm_source,''))='google' AND LOWER(COALESCE(l.utm_medium,'')) LIKE '%cpc%') THEN 'Google Ads'
      WHEN (l.fbclid IS NOT NULL AND l.fbclid<>'') OR (l.accumulated_fbclids IS NOT NULL AND l.accumulated_fbclids<>'')
           OR LOWER(COALESCE(l.utm_source,'')) IN ('fb','facebook','meta','ig','instagram') THEN 'Meta'   -- FB click id catches click-to-WhatsApp leads re-tagged as organic (mid-Jun UTM change)
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('organic','blog','google') THEN 'Organic'
      ELSE 'Other' END AS channel,
    CASE
      WHEN LOWER(COALESCE(l.utm_campaign,''))='inbound_call' THEN 'call'
      WHEN LOWER(COALESCE(l.utm_source,''))='practo' THEN 'book'
      WHEN LOWER(COALESCE(l.utm_campaign,'')) LIKE '%gmb_wa' THEN 'wa_gmb'
      WHEN LOWER(COALESCE(l.utm_campaign,'')) LIKE '%organic_wa' THEN 'wa_org'
      WHEN RIGHT(LOWER(COALESCE(l.utm_campaign,'')),3)='_wa' OR LOWER(COALESCE(l.origin,'')) LIKE '%whatsapp%' THEN 'whatsapp'
      WHEN COALESCE(l.source_url,'')<>'' OR LOWER(COALESCE(l.utm_campaign,'')) IN ('website','blog')
           OR LOWER(COALESCE(l.utm_campaign,'')) LIKE '%-clinic-gmb' THEN 'web'
      ELSE 'other' END AS medium,
    CASE WHEN LOWER(COALESCE(l.utm_campaign,''))='inbound_call'
         THEN RIGHT(REGEXP_REPLACE(COALESCE(l.utm_medium,''),'[^0-9]',''),10) ELSE '' END AS number,
    CASE WHEN COALESCE(l.source_url,'')<>'' THEN LEFT(REGEXP_REPLACE(COALESCE(l.source_url,''),'[?#].*$',''),90) ELSE '' END AS url,
    CASE WHEN cai.cat IN ('SEXUAL_HEALTH_GENERAL','STI','MENTAL_HEALTH') THEN 'in-scope'
         WHEN cai.cat='OTHER' THEN 'out-of-scope' ELSE 'unknown' END AS relevance,
    COALESCE(cai.intent,'') AS intent,
    COALESCE(cai.strength,'') AS strength,
    CASE WHEN cai.cat='SEXUAL_HEALTH_GENERAL' THEN 'SH' WHEN cai.cat='MENTAL_HEALTH' THEN 'MH'
         WHEN cai.cat='STI' THEN 'STI' WHEN cai.cat='OTHER' THEN 'Other'
         WHEN cai.cat IS NOT NULL THEN 'unknown' ELSE 'na' END AS category
  FROM allo_persons.lead l
  LEFT JOIN call_ai cai ON cai.ph = RIGHT(REGEXP_REPLACE(COALESCE(l.phone_no,''),'[^0-9]',''),10)
  LEFT JOIN loc plc ON plc.code = l.location
  LEFT JOIN gmbnum gn ON gn.num = RIGHT(REGEXP_REPLACE(COALESCE(l.utm_medium,''),'[^0-9]',''),10)
  LEFT JOIN citymap ucm ON ucm.tok = SPLIT_PART(REGEXP_SUBSTR(LOWER(COALESCE(l.source_url,'')),
                             '/(sexual-health|mental-health|sti-testing|clinics)/[a-z-]+'),'/',3)
  LEFT JOIN gmbslug gs ON LOWER(COALESCE(l.utm_campaign,'')) LIKE '%-clinic-gmb'
       AND gs.slug = REGEXP_REPLACE(REGEXP_REPLACE(LOWER(COALESCE(l.utm_campaign,'')),'-clinic-gmb$',''),'[^a-z0-9]','')
  LEFT JOIN tokcity tc ON LOWER(COALESCE(l.utm_campaign,'')) SIMILAR TO 't[12]_%'
       AND tc.tok = REGEXP_REPLACE(SPLIT_PART(LOWER(COALESCE(l.utm_campaign,'')),'_',2),'[^a-z0-9]','')
  LEFT JOIN loccity lcb ON lcb.locality = cai.locality
  WHERE l.deleted_at IS NULL AND l.created_at >= '2026-01-05' AND l.created_at < '2026-07-13'
    AND NOT (lower(coalesce(l.utm_medium,''))='clinic' AND lower(coalesce(l.utm_campaign,''))='website')   -- drop the organic/clinic/website bot flood (250k fake +91 leads to /clinics/ pages in wk 6-12 Jul; legit is only ~60/wk)
),
booked AS (   -- phone -> earliest SC booking date per city (for the lead->booking lag)
  SELECT ph, city, MIN(bd) AS bd FROM (
    SELECT RIGHT(REGEXP_REPLACE(COALESCE(p.phone_no,''),'[^0-9]',''),10) AS ph,
           COALESCE(cm.city, INITCAP(loc.city)) AS city, DATE(a.start_time + INTERVAL '5.5 hours') AS bd
    FROM allo_consultations.appointments a
    JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
    JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
    LEFT JOIN citymap cm ON cm.tok = LOWER(loc.city)
    JOIN allo_persons.patient p ON p.id=a.patient_id
    WHERE a.deleted_at IS NULL
  ) q GROUP BY ph, city
),
booked_any AS (   -- phone -> earliest SC booking ANYWHERE (used for no-city leads: they have no city to match against)
  SELECT RIGHT(REGEXP_REPLACE(COALESCE(p.phone_no,''),'[^0-9]',''),10) AS ph, MIN(DATE(a.start_time + INTERVAL '5.5 hours')) AS bd
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_persons.patient p ON p.id=a.patient_id
  WHERE a.deleted_at IS NULL
  GROUP BY 1
),
booked_online AS (   -- phone booked an ONLINE (telehealth) SC anywhere = the 2 telehealth UUIDs (sheet definition)
  SELECT DISTINCT RIGHT(REGEXP_REPLACE(COALESCE(p.phone_no,''),'[^0-9]',''),10) AS ph
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_persons.patient p ON p.id=a.patient_id
  WHERE a.deleted_at IS NULL AND a.location_id IN ('c7d8c9d2-f389-4e8f-a260-71110195b83f','ffe8d849-3099-48fe-a2df-e324c4befe56')
),
booked_offline_any AS (   -- phone booked a PHYSICAL (offline) SC anywhere = NOT the 2 telehealth UUIDs
  SELECT DISTINCT RIGHT(REGEXP_REPLACE(COALESCE(p.phone_no,''),'[^0-9]',''),10) AS ph
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_persons.patient p ON p.id=a.patient_id
  WHERE a.deleted_at IS NULL AND a.location_id NOT IN ('c7d8c9d2-f389-4e8f-a260-71110195b83f','ffe8d849-3099-48fe-a2df-e324c4befe56')
),
verified AS (   -- phone that has an Allo patient record (a patient_id was created), regardless of booking → "verified lead"
  SELECT DISTINCT RIGHT(REGEXP_REPLACE(COALESCE(phone_no,''),'[^0-9]',''),10) AS ph
  FROM allo_persons.patient WHERE deleted_at IS NULL AND COALESCE(phone_no,'') <> ''
)
SELECT COALESCE(la.city,'— no city · online / untracked') AS city, COALESCE(la.locality,'') AS locality, la.channel, la.medium, la.number, la.url, la.relevance, la.intent, la.strength, la.category,
  -- attributed leads: booked = booked IN THAT CITY (b). No-city leads: booked = booked ANYWHERE (ba), since there is no city to match.
  CASE WHEN (CASE WHEN la.city IS NULL THEN ba.bd ELSE b.bd END) IS NULL THEN 'notbooked'
       WHEN DATEDIFF(day, la.created, CASE WHEN la.city IS NULL THEN ba.bd ELSE b.bd END) < 0 THEN 'prior'
       WHEN DATEDIFF(day, la.created, CASE WHEN la.city IS NULL THEN ba.bd ELSE b.bd END) <= 6 THEN 'w0'
       WHEN DATEDIFF(day, la.created, CASE WHEN la.city IS NULL THEN ba.bd ELSE b.bd END) <= 13 THEN 'w1'
       ELSE 'later' END AS status,
  CASE WHEN v.ph IS NOT NULL THEN 'y' ELSE 'n' END AS verified,          -- patient_id created for this lead's phone
  CASE WHEN (la.city IS NOT NULL AND b.bd IS NOT NULL) OR (la.city IS NULL AND bofa.ph IS NOT NULL) THEN 'offline'   -- booked a physical SC (city-matched, or any offline for no-city leads)
       WHEN bo.ph IS NOT NULL THEN 'online'                             -- else booked an online telehealth SC
       ELSE 'none' END AS bkseg,
  la.created, COUNT(DISTINCT la.ph) AS n
FROM lead_attr la
  LEFT JOIN booked b ON b.ph=la.ph AND b.city=la.city
  LEFT JOIN booked_any ba ON ba.ph=la.ph
  LEFT JOIN booked_online bo ON bo.ph=la.ph
  LEFT JOIN booked_offline_any bofa ON bofa.ph=la.ph
  LEFT JOIN verified v ON v.ph=la.ph
WHERE la.channel IS NOT NULL AND la.ph <> ''
GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12,13,14 ORDER BY 1,3;
"""

def run(sql, tries=4):
    # Guard against the occasional hung Redshift Data API statement: time out and retry rather than block forever.
    for attempt in range(tries):
        try:
            p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True, timeout=500)
        except subprocess.TimeoutExpired:
            sys.stderr.write(f'    [retry] query timed out (attempt {attempt+1}/{tries})\n'); sys.stderr.flush(); continue
        if p.returncode != 0 or 'FAIL' in p.stderr:
            if attempt < tries - 1:
                sys.stderr.write(f'    [retry] query failed (attempt {attempt+1}/{tries})\n'); sys.stderr.flush(); continue
            sys.exit('query failed: ' + (p.stderr or '')[:500])
        return [l.split('\t') for l in p.stdout.splitlines() if l.strip()]
    sys.exit('query failed after %d timeouts' % tries)

def main():
    gmbslug_rows = ' UNION ALL '.join(f"SELECT '{s}' AS slug, '{c}' AS city, '{l}' AS locality" for s, (c, l) in GMB_SLUG.items())
    tokcity_rows = ' UNION ALL '.join(f"SELECT '{t}' AS tok, '{c}' AS city" for t, c in TOK_CITY.items())
    loccity_rows = ' UNION ALL '.join(f"SELECT '{l}' AS locality, '{c}' AS city" for l, c in LOC2CITY.items())
    sql = (SQL.replace('{GMBNUM}', gmbvalues())
              .replace('{CITYMAP}', values(CITYMAP.items(), 'tok', 'city'))
              .replace('{GMBSLUG}', gmbslug_rows)
              .replace('{TOKCITY}', tokcity_rows)
              .replace('{LOCCITY}', loccity_rows))
    rows = run(sql)
    cube = defaultdict(lambda: defaultdict(lambda: {'w': [0]*N, 'd': [0]*ND}))   # city -> key -> {weekly(27), daily(recent 8wk)}
    for r in rows:
        if len(r) < 15:
            continue
        city, loc, ch, md, num, url, rel, intent, strength, cat, status, vf, bkseg, created, n = r[:15]
        if ch not in CHANNELS:
            continue
        try:
            wkm = wk_monday(created)
        except Exception:
            continue
        n = int(n)
        acc = cube[city][(loc, ch, md, num, url, rel, intent, strength, cat, status, vf, bkseg)]
        if wkm in WI:
            acc['w'][WI[wkm]] += n
        if created in DI:
            acc['d'][DI[created]] += n
    out = {'_meta': {'weeks': WEEKS, 'days': DAYS, 'channels': CHANNELS, 'mediums': ['call', 'web', 'book', 'whatsapp', 'wa_gmb', 'wa_org'],
                     'preview': False, 'level': 'city',
                     'note': 'Attributable leads by CITY. Each cell has weekly w[] (26 wks, aligned with bookings) + daily d[] '
                             '(recent 8 wks incl. the current partial week, for day-of-week / week-to-date comparison).'}}
    for city, cells in cube.items():
        out[city] = {'cells': [{'loc': loc, 'ch': ch, 'md': md, 'num': num, 'url': url, 'rel': rel, 'int': it, 'istr': istr, 'cat': cat, 'bk': st, 'vf': vf, 'bkseg': seg, 'w': v['w'], 'd': v['d']}
                               for (loc, ch, md, num, url, rel, it, istr, cat, st, vf, seg), v in cells.items()]}
    json.dump(out, open(os.path.join(ROOT, 'data_leads_city.json'), 'w'), separators=(',', ':'))
    n8 = min(8, N)
    for city in sorted(cube, key=lambda c: -sum(sum(v['w'][:n8]) for v in cube[c].values())):
        tot = sum(sum(v['w'][:n8]) for v in cube[city].values())
        bych = defaultdict(int)
        for (ch, *_r), v in cube[city].items():
            bych[ch] += sum(v['w'][:n8])
        print(f'{city:14} {tot:5} leads/8wk · ' + ' '.join(f'{ch}:{bych[ch]}' for ch in CHANNELS if bych[ch]))
    print('wrote data_leads_city.json ·', len(cube), 'cities')

if __name__ == '__main__':
    main()
