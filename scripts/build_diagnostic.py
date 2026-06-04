#!/usr/bin/env python3
"""Build data_diagnostic.json (the diagnostic's core: bookings + new/repeat + weekend split +
booked→done disposition + post-shrinkage availability) from Redshift. Reproducible — replaces the
earlier inline assembly. Needs AWS_PROFILE=redshift-data (SSO).

Run:  python3 scripts/build_diagnostic.py
"""
import os, sys, json, subprocess, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, "scripts", "redshift_query.py")
WK = ['2026-05-25','2026-05-18','2026-05-11','2026-05-04','2026-04-27','2026-04-20',
      '2026-04-13','2026-04-06','2026-03-30','2026-03-23','2026-03-16','2026-03-09']
WI = {w: i for i, w in enumerate(WK)}

def q(sql_file):
    sql = open(os.path.join(ROOT, "scripts", sql_file)).read()
    out = subprocess.run([sys.executable, RUNNER], input=sql, capture_output=True, text=True)
    if out.returncode != 0 or "FAIL:" in out.stderr:
        sys.exit(f"{sql_file} failed: {out.stderr[:300]}")
    return [ln.split("\t") for ln in out.stdout.splitlines() if ln.strip()]

def main():
    D = {}
    def ensure(k):
        return D.setdefault(k, {f: [0]*12 for f in
            ['allBk','bkWe','bkNew','bkRepeat','bkDone','bkResched','bkMissed','bkCancelled',
             'avail','weekend','docDays','gmbLeads']})
    # bookings + disposition
    for p in q("fetch_diag_bookings.sql"):
        if len(p) < 10: continue
        city, loc, wk, bk, we, nw, rp, done, res, mis, can = (p + ['0'])[:11]
        if wk not in WI: continue
        o = ensure(f"{city}|{loc}"); i = WI[wk]
        o['allBk'][i]=int(bk); o['bkWe'][i]=int(we); o['bkNew'][i]=int(nw); o['bkRepeat'][i]=int(rp)
        o['bkDone'][i]=int(done); o['bkResched'][i]=int(res); o['bkMissed'][i]=int(mis); o['bkCancelled'][i]=int(can)
    # availability (post-shrinkage active doctor-days)
    for p in q("fetch_diag_avail.sql"):
        if len(p) < 5: continue
        city, loc, wk, ad, we = p[:5]
        if wk not in WI: continue
        o = ensure(f"{city}|{loc}"); i = WI[wk]
        o['avail'][i]=int(ad); o['weekend'][i]=int(we); o['docDays'][i]=1 if int(ad) > 0 else 0
    today = datetime.date.today().isoformat()
    res = {'_meta': {'weeks': WK, 'pulled': today,
        'source': 'Redshift: allBk=distinct(patient,provider) SC-offline by start-week = bkNew+bkRepeat; '
                  'bkWe=weekend; bkDone/bkResched/bkMissed/bkCancelled=disposition; avail=post-shrinkage active doctor-days'}}
    for k in sorted(D): res[k] = D[k]
    json.dump(res, open(os.path.join(ROOT, "data_diagnostic.json"), "w"), separators=(',', ':'))
    print(f"data_diagnostic.json · {len(D)} clinics · pulled {today}")

if __name__ == "__main__":
    main()
