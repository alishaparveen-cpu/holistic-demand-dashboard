#!/usr/bin/env python3
"""Build data_notbooked.json — leads ATTRIBUTED to a clinic that did NOT book an SC, by channel & week.
Attribution (only where a clinic can be inferred from the lead itself, no agent disposition):
  GMB     — utm_source=gmb AND (utm_medium = the clinic's GMB number  OR  utm_campaign contains the clinic slug)
  Anyone  — ANY lead whose call AI-audit named THIS clinic (is_our_locality, best_match=locality), attributed by the
            lead's real source: Google Ads (gclid/cpc), Organic, Meta, Practo, or Other (justdial/referral/direct/…).
  (Web leads that never call carry only the city, not the clinic → excluded. GMB call/web don't need the audit.)
booked = that phone has EVER booked an SC at this clinic; not_booked = attributed lead whose phone never booked here.
ALL 60 clinics — GMB number→clinic map from data_gmb_number_clinic.json (built from exophone_categorisation.xlsx).
Run: AWS_PROFILE=redshift-data python3 scripts/build_notbooked.py   (needs SSO; loops one query per clinic)
"""
import os, sys, json, subprocess, datetime
from collections import defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, 'scripts', 'redshift_query.py')
WEEKS = ['2026-07-06','2026-06-29','2026-06-22','2026-06-15','2026-06-08','2026-06-01','2026-05-25','2026-05-18',
         '2026-05-11','2026-05-04','2026-04-27','2026-04-20','2026-04-13','2026-04-06','2026-03-30',
         '2026-03-23','2026-03-16','2026-03-09','2026-03-02','2026-02-23','2026-02-16','2026-02-09',
         '2026-02-02','2026-01-26','2026-01-19','2026-01-12']   # weekly axis (26 wks, aligned with bookings — ends 6–12 Jul)
# daily axis: recent 8 weeks incl. the current partial week (for day-of-week / week-to-date compare); current week only lands in d[]
DAY_WEEKS = ['2026-07-06','2026-06-29','2026-06-22','2026-06-15','2026-06-08','2026-06-01','2026-05-25','2026-05-18']
DAYS = []
for _wkm in reversed(DAY_WEEKS):
    _d0 = datetime.date.fromisoformat(_wkm)
    DAYS += [(_d0 + datetime.timedelta(days=_k)).isoformat() for _k in range(7)]
DI = {d: i for i, d in enumerate(DAYS)}; ND = len(DAYS)
def wk_monday(dstr):
    d = datetime.date.fromisoformat(dstr)
    return (d - datetime.timedelta(days=d.weekday())).isoformat()
WI = {w: i for i, w in enumerate(WEEKS)}; N = len(WEEKS)

# per-clinic attribution keys — GMB numbers from data_gmb_number_clinic.json (xlsx), Google via AI-locality (=locality)
def load_clinic_keys():
    gmap = json.load(open(os.path.join(ROOT, 'data_gmb_number_clinic.json')))
    valid = {}   # clinic -> [gmb numbers], skipping pooled/unlabeled rows
    for num, clinic in gmap.items():
        if '|' not in clinic or clinic.split('|', 1)[1].strip().lower() in ('', 'na', 'true', 'none'):
            continue
        valid.setdefault(clinic, []).append(num)
    citycount = defaultdict(int)
    for c in valid:
        citycount[c.split('|')[0].lower()] += 1
    keys = {}
    for clinic, nums in valid.items():
        city, loc = clinic.split('|', 1)
        # GMB web campaigns are '<locality>-clinic-gmb' (multi-clinic cities) or '<city>-clinic-gmb' (single-clinic).
        slugs = [loc.lower().split()[0]]
        if citycount[city.lower()] == 1:               # unambiguous → also match the city name
            cw = city.lower().split()[0]
            if cw not in slugs:
                slugs.append(cw)
        keys[clinic] = {'locality': loc.lower(), 'slugs': slugs, 'gmb_nums': nums}
    return keys
CLINIC_KEYS = load_clinic_keys()

SQL = """
WITH call_loc AS (   -- caller phone -> most-recent AI-audit locality mentioned (for Google clinic attribution)
  SELECT ph, best FROM (
    SELECT RIGHT("from",10) AS ph, LOWER(ca.analysis.user_intent.locality_mentioned.best_match::varchar) AS best,
           ROW_NUMBER() OVER (PARTITION BY RIGHT("from",10) ORDER BY ec.start_time DESC) rn
    FROM allo_analytics.call_analyses ca
    JOIN allo_vendors.exotel_calls ec ON ec.call_id=ca.call_id AND ec.routed_to='lead_to_call' AND ec.direction='inbound'
    WHERE ec.start_time >= '2025-11-01' AND ca.analysis.user_intent.locality_mentioned.is_our_locality = true
  ) q WHERE rn=1
),
call_cat AS (   -- caller phone -> most-recent inbound call's AI category (relevance) + intent + intent-strength
  SELECT ph, cat, intent, strength FROM (
    SELECT RIGHT("from",10) AS ph, ca.analysis.diagnoses.category::varchar AS cat,
           ca.analysis.user_intent.result::varchar AS intent,
           ca.analysis.patient_intent_strength.result::varchar AS strength,
           ROW_NUMBER() OVER (PARTITION BY RIGHT("from",10) ORDER BY ec.start_time DESC) rn
    FROM allo_analytics.call_analyses ca
    JOIN allo_vendors.exotel_calls ec ON ec.call_id=ca.call_id AND ec.routed_to='lead_to_call' AND ec.direction='inbound'
    WHERE ec.start_time >= '2025-11-01'
  ) q WHERE rn=1
),
lead_attr AS (
  SELECT l.id, RIGHT(REGEXP_REPLACE(COALESCE(l.phone_no,''),'[^0-9]',''),10) AS ph,
    TO_CHAR(DATE_TRUNC('week', l.created_at + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
    DATE(l.created_at + INTERVAL '5.5 hours') AS created,
    CASE
      WHEN LOWER(COALESCE(l.utm_source,''))='gmb'
           AND (RIGHT(REGEXP_REPLACE(COALESCE(l.utm_medium,''),'[^0-9]',''),10) IN ({GMBNUMS})  -- GMB call: the number
                OR ({CAMPLIKE})) THEN 'GMB'   -- GMB web: campaign '<locality|city>-clinic-gmb'
      WHEN LOWER(COALESCE(l.utm_source,''))='practo'   -- Practo lead (call OR book OR web) → clinic via its Practo location code
           AND l.location IN ({LOCCODES}) THEN 'Practo'
      WHEN cl.best = '{LOCALITY}' THEN   -- ANY caller whose AI-audit named THIS clinic → attribute, keep the lead's real source
        CASE
          WHEN (l.gclid IS NOT NULL AND l.gclid<>'')
               OR (LOWER(COALESCE(l.utm_source,''))='google' AND LOWER(COALESCE(l.utm_medium,'')) LIKE '%cpc%') THEN 'Google Ads'
          WHEN LOWER(COALESCE(l.utm_source,'')) IN ('gmb','googlelisting','google listing','google_listing') THEN 'GMB'
          WHEN (l.fbclid IS NOT NULL AND l.fbclid<>'') OR (l.accumulated_fbclids IS NOT NULL AND l.accumulated_fbclids<>'')
               OR LOWER(COALESCE(l.utm_source,'')) IN ('fb','facebook','meta','ig','instagram') THEN 'Meta'   -- FB click id (click-to-WhatsApp leads re-tagged organic)
          WHEN LOWER(COALESCE(l.utm_source,'')) IN ('organic','blog','google') THEN 'Organic'   -- organic-google (no gclid/cpc) lands here
          ELSE 'Other' END                 -- justdial, referral, direct, untracked — folded into Other
    END AS channel,
    CASE   -- medium: GMB call/web ; inbound calls ; Practo book vs web ; else caller
      WHEN LOWER(COALESCE(l.utm_source,''))='gmb'
           AND RIGHT(REGEXP_REPLACE(COALESCE(l.utm_medium,''),'[^0-9]',''),10) IN ({GMBNUMS}) THEN 'call'
      WHEN LOWER(COALESCE(l.utm_source,''))='gmb' AND ({CAMPLIKE}) THEN 'web'
      WHEN LOWER(COALESCE(l.utm_campaign,''))='inbound_call' THEN 'call'
      WHEN LOWER(COALESCE(l.utm_source,''))='practo' THEN 'book'   -- Practo non-call = booking (patient-booked + staff-entered dashboard)
      ELSE 'call' END AS medium,
    CASE WHEN LOWER(COALESCE(l.utm_campaign,''))='inbound_call'   -- the exact number the caller dialed (exophone)
         THEN RIGHT(REGEXP_REPLACE(COALESCE(l.utm_medium,''),'[^0-9]',''),10) ELSE '' END AS number,
    CASE WHEN LOWER(COALESCE(l.utm_source,''))='gmb' AND ({CAMPLIKE})   -- GMB-web landing page (exact URL)
         THEN LEFT(REGEXP_REPLACE(COALESCE(l.source_url,''),'[?#].*$',''), 90) ELSE '' END AS url,
    CASE   -- RELEVANCE from the call's AI diagnosis category (per phone — a web lead whose phone also called keeps that audit, by design)
      WHEN cc.cat IN ('SEXUAL_HEALTH_GENERAL','STI','MENTAL_HEALTH') THEN 'in-scope'
      WHEN cc.cat = 'OTHER' THEN 'out-of-scope'          -- AI flagged the concern as outside Allo's lines of care
      ELSE 'unknown' END AS relevance,                   -- web lead / unaudited call / category not-mentioned
    COALESCE(cc.intent,'') AS intent,                    -- what the caller wanted (AI): TALK_TO_DOCTOR / NEEDS_TESTS / …
    COALESCE(cc.strength,'') AS strength,                -- AI patient_intent_strength: STRONG / LOW / COULD_NOT_DETERMINE / NOT_A_PATIENT
    CASE WHEN cc.cat='SEXUAL_HEALTH_GENERAL' THEN 'SH' WHEN cc.cat='MENTAL_HEALTH' THEN 'MH'
         WHEN cc.cat='STI' THEN 'STI' WHEN cc.cat='OTHER' THEN 'Other'
         WHEN cc.cat IS NOT NULL THEN 'unknown' ELSE 'na' END AS category   -- AI diagnosis category of the call
  FROM allo_persons.lead l
  LEFT JOIN call_loc cl ON cl.ph = RIGHT(REGEXP_REPLACE(COALESCE(l.phone_no,''),'[^0-9]',''),10)
  LEFT JOIN call_cat cc ON cc.ph = RIGHT(REGEXP_REPLACE(COALESCE(l.phone_no,''),'[^0-9]',''),10)
  WHERE l.deleted_at IS NULL AND l.created_at >= '2026-01-05' AND l.created_at < '2026-07-13'
    AND NOT (lower(coalesce(l.utm_medium,''))='clinic' AND lower(coalesce(l.utm_campaign,''))='website')   -- drop the organic/clinic/website bot flood (250k fake +91 leads in wk 6-12 Jul)
),
booked AS (   -- phone -> earliest SC booking date at this clinic (for the lead->booking lag)
  SELECT ph, MIN(bd) AS bd FROM (
    SELECT RIGHT(REGEXP_REPLACE(COALESCE(p.phone_no,''),'[^0-9]',''),10) AS ph,
           DATE(a.start_time + INTERVAL '5.5 hours') AS bd
    FROM allo_consultations.appointments a
    JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
    JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL AND LOWER(loc.locality)='{LOCALITY}'
    JOIN allo_persons.patient p ON p.id=a.patient_id
    WHERE a.deleted_at IS NULL
  ) q GROUP BY ph
),
booked_online AS (   -- phone that booked an ONLINE (telehealth) Screening Call anywhere → for the offline/online split of booked leads
  SELECT DISTINCT RIGHT(REGEXP_REPLACE(COALESCE(p.phone_no,''),'[^0-9]',''),10) AS ph
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_persons.patient p ON p.id=a.patient_id
  WHERE a.deleted_at IS NULL AND a.location_id IN ('c7d8c9d2-f389-4e8f-a260-71110195b83f','ffe8d849-3099-48fe-a2df-e324c4befe56')   -- ONLINE = the 2 telehealth UUIDs (sheet definition; was loc.name LIKE '%online%')
),
verified AS (   -- phone that has an Allo patient record (a patient_id was created), regardless of booking → "verified lead"
  SELECT DISTINCT RIGHT(REGEXP_REPLACE(COALESCE(phone_no,''),'[^0-9]',''),10) AS ph
  FROM allo_persons.patient WHERE deleted_at IS NULL AND COALESCE(phone_no,'') <> ''
),
done_c AS (   -- phone that COMPLETED an SC at THIS clinic (ever) → the lead's Done? split (mirrors booked)
  SELECT DISTINCT RIGHT(REGEXP_REPLACE(COALESCE(p.phone_no,''),'[^0-9]',''),10) AS ph
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL AND LOWER(loc.locality)='{LOCALITY}'
  JOIN allo_persons.patient p ON p.id=a.patient_id
  WHERE a.deleted_at IS NULL AND LOWER(a.status) IN ('completed','reconsulted')
)
SELECT la.created, la.channel, la.medium, la.number, la.url, la.relevance, la.intent, la.strength, la.category,
  CASE WHEN b.ph IS NULL THEN 'notbooked'                                -- lag bucket: UI dropdown picks the window
       WHEN DATEDIFF(day, la.created, b.bd) < 0 THEN 'prior'             -- booked before this lead (repeat patient)
       WHEN DATEDIFF(day, la.created, b.bd) <= 6 THEN 'w0'               -- same week
       WHEN DATEDIFF(day, la.created, b.bd) <= 13 THEN 'w1'              -- within 2 weeks
       ELSE 'later' END AS status,
  CASE WHEN v.ph IS NOT NULL THEN 'y' ELSE 'n' END AS verified,          -- patient_id created for this lead's phone
  CASE WHEN b.ph IS NOT NULL THEN 'offline'                              -- booked an SC at THIS clinic (physical)
       WHEN bo.ph IS NOT NULL THEN 'online'                             -- else booked an online telehealth SC
       ELSE 'none' END AS bkseg,                                         -- where the booked lead booked (offline clinic / online / not booked)
  CASE WHEN d.ph IS NOT NULL THEN 'done' ELSE 'notdone' END AS doneq,     -- did this lead's phone COMPLETE an SC at this clinic (ever)?
  COUNT(DISTINCT la.ph) AS n    -- UNIQUE PATIENTS (by phone) per week, not raw lead records
FROM lead_attr la LEFT JOIN booked b ON b.ph=la.ph LEFT JOIN booked_online bo ON bo.ph=la.ph LEFT JOIN verified v ON v.ph=la.ph LEFT JOIN done_c d ON d.ph=la.ph
WHERE la.channel IS NOT NULL AND la.ph <> ''
GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12,13 ORDER BY 1,2,3;
"""

def run(sql, tries=4):
    # Redshift Data API occasionally leaves a statement hung (describe-statement never returns). A healthy query is ~30s,
    # so time out at 150s and retry — the retry reliably succeeds — instead of blocking the whole sequential build forever.
    for attempt in range(tries):
        try:
            p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            sys.stderr.write(f'    [retry] query timed out (attempt {attempt+1}/{tries})\n'); sys.stderr.flush(); continue
        if p.returncode != 0 or 'FAIL' in p.stderr:
            if attempt < tries - 1:
                sys.stderr.write(f'    [retry] query failed (attempt {attempt+1}/{tries})\n'); sys.stderr.flush(); continue
            sys.exit('query failed: ' + (p.stderr or '')[:400])
        return [l.split('\t') for l in p.stdout.splitlines() if l.strip()]
    sys.exit('query failed after %d timeouts' % tries)

CHANNELS = ['GMB', 'Google Ads', 'Meta', 'Practo', 'Organic', 'Other']
def main():
    note = ('GMB=clinic GMB number/campaign (call+web). Everyone else = a caller whose AI-audit named THIS clinic '
            '(is_our_locality), attributed by the lead\'s real source: Google Ads(paid), Organic, Meta, Practo, '
            'or Other (justdial/referral/direct/untracked). Web leads that never call carry only the city → excluded.')
    nb = {'_meta': {'weeks': WEEKS, 'channels': CHANNELS,
                    'note': 'Leads attributed to the clinic that did NOT book an SC. ' + note}}   # aggregated
    leads = {'_meta': {'weeks': WEEKS, 'days': DAYS, 'channels': CHANNELS, 'mediums': ['call', 'web'],
                       'preview': False, 'note': 'Attributable leads cube: channel x medium x booked-status x week. ' + note}}
    # locality -> Practo location code(s), for Practo book/web/call attribution
    loc_codes = defaultdict(list)
    for r in run("SELECT LOWER(locality) AS l, code FROM allo_health.locations WHERE deleted_at IS NULL AND code IS NOT NULL AND code <> '';"):
        if len(r) >= 2 and r[1]:
            loc_codes[r[0]].append(r[1])
    for clinic, k in CLINIC_KEYS.items():
        camplike = ' OR '.join(f"LOWER(COALESCE(l.utm_campaign,'')) LIKE '%{s}%'" for s in k['slugs'])
        codes = loc_codes.get(k['locality'], [])
        loccodes = ','.join(f"'{c}'" for c in codes) or "'__none__'"
        sql = (SQL.replace('{GMBNUMS}', ','.join(f"'{n}'" for n in k['gmb_nums']))
                  .replace('{CAMPLIKE}', camplike).replace('{LOCCODES}', loccodes).replace('{LOCALITY}', k['locality']))
        rows = run(sql)
        cube = defaultdict(lambda: {'w': [0]*N, 'd': [0]*ND})   # key -> {weekly(26), daily(recent 8wk incl. current partial week)}
        node = {ch: {'leads': [0]*N, 'booked': [0]*N, 'notbooked': [0]*N} for ch in CHANNELS}
        for r in rows:
            if len(r) < 14:
                continue
            created, ch, md, number, url, rel, intent, strength, cat, status, vf, bkseg, doneq, n = r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11], r[12], int(r[13])
            if ch not in node:
                continue
            try:
                wkm = wk_monday(created)
            except Exception:
                continue
            acc = cube[(ch, md, number, url, rel, intent, strength, cat, status, vf, bkseg, doneq)]
            if wkm in WI:
                i = WI[wkm]
                acc['w'][i] += n
                node[ch]['leads'][i] += n
                node[ch]['notbooked' if status == 'notbooked' else 'booked'][i] += n   # lag buckets fold to ever-booked for data_notbooked.json
            if created in DI:
                acc['d'][DI[created]] += n
        leads[clinic] = {'cells': [{'ch': ch, 'md': md, 'num': num, 'url': url, 'rel': rel, 'int': intent, 'istr': istr, 'cat': cat, 'bk': st, 'vf': vf, 'bkseg': seg, 'dq': dq, 'w': v['w'], 'd': v['d']}
                                   for (ch, md, num, url, rel, intent, istr, cat, st, vf, seg, dq), v in cube.items()]}
        nb[clinic] = node
        n8 = min(8, N)
        tot8 = sum(sum(node[ch]['leads'][:n8]) for ch in CHANNELS)
        print(f'{clinic} · last {n8} wks · {tot8} leads:')
        for ch in CHANNELS:
            L = sum(node[ch]['leads'][:n8]); B = sum(node[ch]['booked'][:n8]); NB = sum(node[ch]['notbooked'][:n8])
            if L:
                print(f'  {ch:11} leads {L:4} · booked {B:4} · NOT booked {NB:4}')
    json.dump(leads, open(os.path.join(ROOT, 'data_leads.json'), 'w'), separators=(',', ':'))
    json.dump(nb, open(os.path.join(ROOT, 'data_notbooked.json'), 'w'), separators=(',', ':'))
    print('wrote data_leads.json + data_notbooked.json')

if __name__ == '__main__':
    main()
