#!/usr/bin/env python3
"""Pull Google/GMB reviews with TEXT from allo_health.external_reviews and category-tag each
(STI / SH / MH) by keyword → per-clinic weekly velocity. Writes data_gmb_review_cat.json,
consumed by build_gmb_cube.py to fill the GMB tab's rev_cat (category-specific reviews) section.

Reality: most reviews are general service feedback ("great doctor, very supportive") with NO clinical
signal → they land in 'general'. Category buckets grow slowly as patients mention their concern.
Weeks axis aligned to data_gmb_insights.json. Auth: AWS_PROFILE=redshift-data.
"""
import boto3, os, time, sys, json, re, datetime
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INS = json.load(open(os.path.join(ROOT, 'data_gmb_insights.json')))
WEEKS = INS['_meta']['weeks']; NW = len(WEEKS); WIDX = {w: i for i, w in enumerate(WEEKS)}
SINCE = WEEKS[-1]   # oldest Monday in the axis

# keyword sets (word-ish; avoid bare 'ed'/'pe'/'sex' that match common words)
STI = ('hiv', 'std', 'sti', 'syphilis', 'gonorrh', 'herpes', 'chlamyd', 'hpv', 'genital wart',
       'urine infection', 'urinary infection', 'discharge', 'burning urin')
MH  = ('anxiet', 'depress', 'stress', 'mental health', 'psychiatr', 'psycholog', 'therapy', 'counsel',
       'panic', 'mood', 'ocd', 'bipolar', 'insomnia', 'sleep problem')
SH  = ('erectile', 'premature', 'ejaculat', 'libido', 'sexolog', 'sexual', 'penis', 'testosteron',
       'performance anxiety', 'nightfall', 'masturbat', 'porn', 'stamina', 'low sperm', 'infertil')
def cat_of(txt):
    t = (txt or '').lower()
    if any(k in t for k in STI): return 'STI'
    if any(k in t for k in MH):  return 'MH'
    if any(k in t for k in SH):  return 'SH'
    return 'general'

SQL = f"""
SELECT loc.city, loc.locality,
       TO_CHAR(DATE_TRUNC('week', er.review_date + INTERVAL '5.5 hours')::date,'YYYY-MM-DD') AS wk,
       er.review AS txt
FROM allo_health.external_reviews er
JOIN allo_health.locations loc ON loc.id = er.reviewed_for_id AND loc.deleted_at IS NULL
WHERE er.deleted_at IS NULL AND LOWER(er.platform) IN ('google','gmb')
  AND er.review_date >= '{SINCE}' AND COALESCE(er.review,'') <> '';
"""

def main():
    cli = boto3.Session(profile_name=os.environ.get("AWS_PROFILE")).client("redshift-data", region_name="ap-south-1")
    rid = cli.batch_execute_statement(ClusterIdentifier="warehouse", Database="allo_prod",
                                      DbUser="redshift_admin", Sqls=[SQL])["Id"]
    while True:
        time.sleep(1.5); d = cli.describe_statement(Id=rid)
        if d["Status"] == "FINISHED": break
        if d["Status"] in ("FAILED", "ABORTED"): sys.exit("FAIL: " + str(d.get("Error"))[:300])
    sub = d["SubStatements"][-1]["Id"] if d.get("SubStatements") else rid
    rows = []; tok = None
    while True:
        kw = dict(Id=sub);  tok and kw.update(NextToken=tok)
        p = cli.get_statement_result(**kw)
        for r in p["Records"]:
            rows.append([("" if (not c or c.get("isNull")) else list(c.values())[0]) for c in r])
        tok = p.get("NextToken")
        if not tok: break

    out = defaultdict(lambda: {c: [0]*NW for c in ('SH', 'STI', 'MH', 'general')})
    tagged = 0
    for city, loc, wk, txt in rows:
        if wk not in WIDX or not loc: continue
        c = cat_of(txt)
        out[f'{city}|{loc}'][c][WIDX[wk]] += 1
        if c != 'general': tagged += 1
    out = {k: v for k, v in out.items()}
    json.dump({'_meta': {'weeks': WEEKS, 'note': 'category-tagged review velocity (keyword on review text); general = no clinical signal'},
               'clinics': out}, open(os.path.join(ROOT, 'data_gmb_review_cat.json'), 'w'), separators=(',', ':'))
    tot = len(rows)
    print(f'wrote data_gmb_review_cat.json · {len(out)} clinics · {tot} reviews · {tagged} category-tagged ({100*tagged/max(1,tot):.0f}%)')
    agg = defaultdict(int)
    for v in out.values():
        for c in ('SH', 'STI', 'MH', 'general'):
            agg[c] += sum(v[c])
    print('national totals by category:', dict(agg))

if __name__ == '__main__':
    main()
