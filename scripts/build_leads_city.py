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
# DYNAMIC weekly axis — auto-advances every Monday; grid[0] = latest COMPLETE Mon–Sun week (never the in-progress one).
_TDY = datetime.date.today(); _MON = _TDY - datetime.timedelta(days=_TDY.weekday())   # Monday of the current (in-progress) week
_CUTOFF = _MON.isoformat()   # exclusive upper bound on created_at → excludes the in-progress week
def _wkgrid(n): return [(_MON - datetime.timedelta(weeks=i + 1)).isoformat() for i in range(n)]
WEEKS = _wkgrid(27)   # weekly axis (27 wks)
WI = {w: i for i, w in enumerate(WEEKS)}; N = len(WEEKS)
# daily axis: recent 8 weeks INCLUDING the current (partial) week 2026-07-06 — powers the day-of-week / week-to-date comparison.
# Kept separate from WEEKS so the weekly axis stays aligned with the bookings cube; current-week leads land only in d[].
DAY_WEEKS = _wkgrid(9)
DAYS = []
for _wkm in reversed(DAY_WEEKS):
    _d0 = datetime.date.fromisoformat(_wkm)
    DAYS += [(_d0 + datetime.timedelta(days=_k)).isoformat() for _k in range(7)]
DI = {d: i for i, d in enumerate(DAYS)}; ND = len(DAYS)
def wk_monday(dstr):
    d = datetime.date.fromisoformat(dstr)
    return (d - datetime.timedelta(days=d.weekday())).isoformat()
CHANNELS = ['GMB', 'Google Ads', 'Meta', 'Practo', 'Organic', 'Organic · Blog', 'Other']

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
terr AS (   -- Marketing 'Territory' registry (allo_health.territory): each city's inbound phone line -> canonical city.
            -- Authoritative number->city map (179 territories, 29 city lines w/ phones) -> attribute CALL leads by the number
            -- dialed instead of relying on the AI audit. City-level only (no locality). Normalised via citymap.
    SELECT RIGHT(REGEXP_REPLACE(t.phone_no,'[^0-9]',''),10) AS num,
           COALESCE(cm.city, INITCAP(t.name)) AS city
    FROM allo_health.territory t
    LEFT JOIN citymap cm ON cm.tok = LOWER(t.name)
    WHERE t.deleted_at IS NULL AND t.territory_type='city'
      AND t.phone_no IS NOT NULL AND t.phone_no<>'' AND t.is_active=1
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
    -- CITY priority: Practo code > GMB clinic-gmb slug > TERRITORY number (dialed city line) > AI user_city > source_url city > GMB number city > Google campaign token > locality backfill
    COALESCE(
      CASE WHEN LOWER(COALESCE(l.utm_source,''))='practo' THEN plc.city END,
      gs.city,
      tn.city,      -- territory registry: the city phone line the caller dialed (authoritative number->city; before AI audit)
      cai.city,
      ucm.city,
      ucm2.city,
      gn.city,
      tc.city,      -- Google T1/T2 campaign-city token: low-priority fallback only (used when no territory number). The Navi-Mumbai-MH shared-line was fixed at source 2026-07-16, so the number itself now carries the right city — no override needed.
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
           OR (LOWER(COALESCE(l.utm_source,''))='google' AND LOWER(COALESCE(l.utm_medium,'')) LIKE '%cpc%')
           OR (LOWER(COALESCE(l.utm_source,''))='google' AND LOWER(COALESCE(l.utm_campaign,''))='inbound_call') THEN 'Google Ads'  -- google-source inbound calls (call-ext/call-only ads): no gclid & medium=number (not cpc) → were wrongly falling to Organic. GMB calls are tagged utm_source='gmb', so no risk of pulling GMB in.
      WHEN (l.fbclid IS NOT NULL AND l.fbclid<>'') OR (l.accumulated_fbclids IS NOT NULL AND l.accumulated_fbclids<>'')
           OR LOWER(COALESCE(l.utm_source,'')) IN ('fb','facebook','meta','ig','instagram') THEN 'Meta'   -- FB click id catches click-to-WhatsApp leads re-tagged as organic (mid-Jun UTM change)
      WHEN LOWER(COALESCE(l.source_url,'')) LIKE '%/blog/%' THEN 'Organic · Blog'   -- any /blog/ landing = blog content (after the paid checks above, so gclid/fbclid blog-landings stay paid); catches null-utm_source blog readers too
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('organic','blog','google') THEN 'Organic'
      ELSE 'Other' END AS channel,   -- remaining Other = bare null-source / no-url direct-untracked records
    CASE
      WHEN LOWER(COALESCE(l.utm_campaign,''))='inbound_call' THEN 'call'
      WHEN LOWER(COALESCE(l.utm_source,''))='practo' THEN 'book'
      WHEN LOWER(COALESCE(l.utm_medium,''))='whatsapp' AND LOWER(COALESCE(l.utm_campaign,''))='outbound' THEN 'wa_outbound'   -- WhatsApp API outbound-template flow (complete: blog is now on the source axis, so blog-driven WhatsApp lands here too)
      WHEN LOWER(COALESCE(l.utm_campaign,'')) LIKE '%gmb_wa' THEN 'wa_gmb'
      WHEN LOWER(COALESCE(l.utm_campaign,'')) LIKE '%organic_wa' THEN 'wa_org'
      WHEN RIGHT(LOWER(COALESCE(l.utm_campaign,'')),3)='_wa' OR LOWER(COALESCE(l.origin,'')) LIKE '%whatsapp%' THEN 'whatsapp'
      WHEN COALESCE(l.source_url,'')<>'' OR LOWER(COALESCE(l.utm_campaign,'')) IN ('website','blog')
           OR LOWER(COALESCE(l.utm_campaign,'')) LIKE '%-clinic-gmb' THEN 'web'
      ELSE 'other' END AS medium,
    CASE WHEN LOWER(COALESCE(l.utm_campaign,''))='inbound_call'
         THEN RIGHT(REGEXP_REPLACE(COALESCE(l.utm_medium,''),'[^0-9]',''),10) ELSE '' END AS number,
    CASE WHEN LOWER(COALESCE(l.utm_campaign,''))='inbound_call' THEN 1 ELSE 0 END AS iscall,   -- dialed a tracked inbound line → connected on a call by definition
    CASE   -- CLUBBED campaign/number dim: call → ☎ number dialed ; paid google/fb → ad campaign name ; else blank
      WHEN LOWER(COALESCE(l.utm_campaign,''))='inbound_call' THEN '☎ '||RIGHT(REGEXP_REPLACE(COALESCE(l.utm_medium,''),'[^0-9]',''),10)
      WHEN (l.gclid IS NOT NULL AND l.gclid<>'') OR (LOWER(COALESCE(l.utm_source,''))='google' AND LOWER(COALESCE(l.utm_medium,'')) LIKE '%cpc%')
           OR (l.fbclid IS NOT NULL AND l.fbclid<>'') OR (l.accumulated_fbclids IS NOT NULL AND l.accumulated_fbclids<>'')
           OR LOWER(COALESCE(l.utm_source,'')) IN ('fb','facebook','meta','ig','instagram')
        THEN COALESCE(NULLIF(l.utm_campaign,''),'(none)') ELSE '' END AS campaign,
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
  LEFT JOIN terr tn ON tn.num = RIGHT(REGEXP_REPLACE(COALESCE(l.utm_medium,''),'[^0-9]',''),10)   -- territory city phone -> city
  LEFT JOIN citymap ucm ON ucm.tok = SPLIT_PART(REGEXP_SUBSTR(LOWER(COALESCE(l.source_url,'')),
                             '/(sexual-health|mental-health|sti-testing|sex-health-clinic|clinics)/[a-z-]+'),'/',3)
  LEFT JOIN citymap ucm2 ON ucm2.tok = REGEXP_SUBSTR(   -- prefix-agnostic fallback: the LAST path segment if it IS a city
                             REGEXP_REPLACE(REGEXP_REPLACE(LOWER(COALESCE(l.source_url,'')),'[?#].*$',''),'/+$',''),   -- strip query + trailing slash
                             '[a-z0-9-]+$')   -- catches /sexologists/<city>, /sexologists-listing/<city>, /std/testing/<city>, bare /<city>; non-city tails (online-roi, self-assessment) don't match citymap so they stay national
  LEFT JOIN gmbslug gs ON LOWER(COALESCE(l.utm_campaign,'')) LIKE '%-clinic-gmb'
       AND gs.slug = REGEXP_REPLACE(REGEXP_REPLACE(LOWER(COALESCE(l.utm_campaign,'')),'-clinic-gmb$',''),'[^a-z0-9]','')
  LEFT JOIN tokcity tc ON LOWER(COALESCE(l.utm_campaign,'')) SIMILAR TO 't[12]_%'
       AND tc.tok = REGEXP_REPLACE(   -- full city span between the T1/T2_ prefix and the _<category>_ token → handles 2-word cities (Navi_Mumbai → navimumbai)
             REGEXP_REPLACE(REGEXP_REPLACE(LOWER(COALESCE(l.utm_campaign,'')),'^t[12]_',''),
                            '_(sh|std|sti|mh|ed|pe|brand|general)(_.*)?$',''),
             '[^a-z0-9]','')
  LEFT JOIN loccity lcb ON lcb.locality = cai.locality
  WHERE l.deleted_at IS NULL AND l.created_at >= '2026-01-05' AND l.created_at < '{CUTOFF}'
    AND NOT (lower(coalesce(l.utm_medium,''))='clinic' AND lower(coalesce(l.utm_campaign,''))='website')   -- drop the organic/clinic/website bot flood (250k fake +91 leads to /clinics/ pages in wk 6-12 Jul; legit is only ~60/wk)
),
lead_book AS (   -- ID JOIN: lead -> ITS patient's SC bookings (patient.lead_id = lead.id). Catches alternate-phone bookings; matches ②'s patient_id book side. (was phone-match)
  SELECT p.lead_id AS lid,
         MIN(DATE(a.start_time + INTERVAL '5.5 hours')) AS bd,   -- earliest SC anywhere (for the lead->book lag)
         MAX(CASE WHEN a.location_id NOT IN ('c7d8c9d2-f389-4e8f-a260-71110195b83f','ffe8d849-3099-48fe-a2df-e324c4befe56') THEN 1 ELSE 0 END) AS any_off,   -- booked a physical SC
         MAX(CASE WHEN a.location_id IN ('c7d8c9d2-f389-4e8f-a260-71110195b83f','ffe8d849-3099-48fe-a2df-e324c4befe56') THEN 1 ELSE 0 END) AS any_onl,      -- booked an online telehealth SC
         MAX(CASE WHEN LOWER(a.status) IN ('completed','reconsulted') THEN 1 ELSE 0 END) AS did_done   -- completed an SC
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_persons.patient p ON p.id=a.patient_id
  WHERE a.deleted_at IS NULL AND p.lead_id IS NOT NULL
  GROUP BY p.lead_id
),
lead_pat AS (   -- verified-lead universe: a patient_id was created FROM this lead (patient.lead_id = lead.id). The funnel is now verified-only.
  SELECT DISTINCT lead_id AS lid FROM allo_persons.patient WHERE deleted_at IS NULL AND lead_id IS NOT NULL
),
called AS (   -- every phone that connected on an INBOUND lead-to-call (exotel) — ground truth for "did this person actually get on a call"
  SELECT DISTINCT RIGHT(REGEXP_REPLACE("from",'[^0-9]',''),10) AS ph
  FROM allo_vendors.exotel_calls WHERE routed_to='lead_to_call' AND direction='inbound' AND start_time >= '2025-11-01' AND "from" IS NOT NULL
),
pat_phone AS (   -- patient created from this lead → their phone (catches an ALTERNATE number, not just the lead's own phone)
  SELECT lead_id AS lid, RIGHT(REGEXP_REPLACE(COALESCE(phone_no,''),'[^0-9]',''),10) AS ph
  FROM allo_persons.patient WHERE deleted_at IS NULL AND lead_id IS NOT NULL
),
lead_conn AS (   -- per-lead: did the lead's OWN phone OR its patient's phone connect on a call, OR is it an inbound-call lead? (MAX → one value per lead)
  SELECT la.id, MAX(CASE WHEN cs.ph IS NOT NULL OR cp.ph IS NOT NULL OR la.iscall=1 THEN 1 ELSE 0 END) AS oncall
  FROM lead_attr la
  LEFT JOIN called cs ON cs.ph = la.ph
  LEFT JOIN pat_phone pp ON pp.lid = la.id
  LEFT JOIN called cp ON cp.ph = pp.ph
  GROUP BY la.id
),
lead_diag AS (   -- CATEGORY BACKFILL: a lead's completed consult carries a clinical diagnosis (encounter_tags). Recovers the TRUE category for leads that were 'uncategorized' at call-intent (mostly web leads that never called). STI>SH precedence; MH has no diagnosis tag so it is NOT recoverable. Applies only to converted leads (a diagnosis implies a done) — read category-mix as improved, but conversion rates on backfilled cats are upward-biased (every backfilled lead is by definition a done).
  SELECT p.lead_id AS lid,
         CASE WHEN MAX(CASE WHEN dg.dcat='STI' THEN 1 ELSE 0 END)=1 THEN 'STI'
              WHEN MAX(CASE WHEN dg.dcat='SH'  THEN 1 ELSE 0 END)=1 THEN 'SH'
              ELSE 'Other' END AS dcat
  FROM allo_consultations.appointments a
  JOIN allo_persons.patient p ON p.id=a.patient_id AND p.deleted_at IS NULL
  JOIN (
    SELECT e.appointment_id,
      CASE WHEN MAX(CASE WHEN et.tag_type='sti' THEN 1 ELSE 0 END)=1 THEN 'STI'
           WHEN MAX(CASE WHEN et.tag_type IN ('ed_plus_pe_plus','ed_plus','pe_plus','nssd') THEN 1 ELSE 0 END)=1 THEN 'SH'
           WHEN MAX(CASE WHEN et.encounter_id IS NOT NULL THEN 1 ELSE 0 END)=1 THEN 'oth'
           ELSE NULL END AS dcat
    FROM allo_encounters.encounters e
    LEFT JOIN allo_analytics.encounter_tags et ON et.encounter_id=e.id AND et.tag_category='diagnosis' AND et.deleted_at IS NULL
    WHERE e.deleted_at IS NULL GROUP BY 1
  ) dg ON dg.appointment_id=a.id AND dg.dcat IS NOT NULL
  WHERE a.deleted_at IS NULL AND p.lead_id IS NOT NULL
  GROUP BY p.lead_id
)
SELECT COALESCE(la.city,'— no city · online / untracked') AS city, COALESCE(la.locality,'') AS locality, la.channel, la.medium, la.number, la.campaign, la.url, la.relevance, la.intent, la.strength,
  CASE WHEN la.category IN ('na','unknown','Other') AND ld.dcat IS NOT NULL THEN ld.dcat ELSE la.category END AS category,
  -- booked via the ID join (patient.lead_id): lag from lead created -> the lead's patient's earliest SC
  CASE WHEN lb.bd IS NULL THEN 'notbooked'
       WHEN DATE_TRUNC('week', lb.bd) < DATE_TRUNC('week', la.created) THEN 'prior'
       WHEN DATEDIFF(week, DATE_TRUNC('week', la.created), DATE_TRUNC('week', lb.bd)) = 0 THEN 'w0'
       WHEN DATEDIFF(week, DATE_TRUNC('week', la.created), DATE_TRUNC('week', lb.bd)) = 1 THEN 'w1'
       ELSE 'later' END AS status,
  'y' AS verified,                                                      -- verified-only funnel (every row has a patient via lead_id)
  CASE WHEN lb.any_off=1 THEN 'offline' WHEN lb.any_onl=1 THEN 'online' ELSE 'none' END AS bkseg,   -- where the booked lead booked (offline priority)
  CASE WHEN lb.did_done=1 THEN 'done' ELSE 'notdone' END AS doneq,      -- the lead's patient completed an SC
  CASE WHEN lc.oncall=1 THEN 'y' ELSE 'n' END AS oncall,                -- connected on a call? (lead OR patient phone in exotel inbound) — independent of medium/source
  la.created, COUNT(DISTINCT la.id) AS n
FROM lead_attr la
  JOIN lead_pat lp ON lp.lid = la.id                                    -- verified-only (drops the ~1% unverified; 0 bookings among them)
  LEFT JOIN lead_book lb ON lb.lid = la.id
  LEFT JOIN lead_conn lc ON lc.id = la.id
  LEFT JOIN lead_diag ld ON ld.lid = la.id
WHERE la.channel IS NOT NULL AND la.ph <> ''
GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17 ORDER BY 1,3;
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
    sql = (SQL.replace('{CUTOFF}', _CUTOFF).replace('{GMBNUM}', gmbvalues())
              .replace('{CITYMAP}', values(CITYMAP.items(), 'tok', 'city'))
              .replace('{GMBSLUG}', gmbslug_rows)
              .replace('{TOKCITY}', tokcity_rows)
              .replace('{LOCCITY}', loccity_rows))
    rows = run(sql)
    cube = defaultdict(lambda: defaultdict(lambda: {'w': [0]*N, 'd': [0]*ND}))   # city -> key -> {weekly(27), daily(recent 8wk)}
    for r in rows:
        if len(r) < 18:
            continue
        city, loc, ch, md, num, campaign, url, rel, intent, strength, cat, status, vf, bkseg, doneq, oncall, created, n = r[:18]
        if ch not in CHANNELS:
            continue
        try:
            wkm = wk_monday(created)
        except Exception:
            continue
        n = int(n)
        acc = cube[city][(loc, ch, md, num, campaign, url, rel, intent, strength, cat, status, vf, bkseg, doneq, oncall)]
        if wkm in WI:
            acc['w'][WI[wkm]] += n
        if created in DI:
            acc['d'][DI[created]] += n
    out = {'_meta': {'weeks': WEEKS, 'days': DAYS, 'channels': CHANNELS, 'mediums': ['call', 'web', 'book', 'whatsapp', 'wa_gmb', 'wa_org', 'wa_outbound'],
                     'preview': False, 'level': 'city',
                     'note': 'Attributable leads by CITY. Each cell has weekly w[] (26 wks, aligned with bookings) + daily d[] '
                             '(recent 8 wks incl. the current partial week, for day-of-week / week-to-date comparison).'}}
    for city, cells in cube.items():
        out[city] = {'cells': [{'loc': loc, 'ch': ch, 'md': md, 'num': num, 'cmp': cmp, 'url': url, 'rel': rel, 'int': it, 'istr': istr, 'cat': cat, 'bk': st, 'vf': vf, 'bkseg': seg, 'dq': dq, 'oc': oc, 'w': v['w'], 'd': v['d']}
                               for (loc, ch, md, num, cmp, url, rel, it, istr, cat, st, vf, seg, dq, oc), v in cells.items()]}
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
