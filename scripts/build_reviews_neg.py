#!/usr/bin/env python3
"""Build data_reviews_neg.json (recent negative Google/GMB reviews per clinic, with text) from
Redshift. Needs AWS_PROFILE=redshift-data (SSO).  Run: python3 scripts/build_reviews_neg.py"""
import os, sys, json, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, "scripts", "redshift_query.py")

def main():
    sql = open(os.path.join(ROOT, "scripts", "fetch_reviews_neg.sql")).read()
    out = subprocess.run([sys.executable, RUNNER], input=sql, capture_output=True, text=True)
    if out.returncode != 0 or "FAIL:" in out.stderr:
        sys.exit("fetch_reviews_neg.sql failed: " + out.stderr[:300])
    D = {}
    for ln in out.stdout.splitlines():
        p = ln.split("\t")
        if len(p) < 6: continue
        city, loc, dt, rating, author, replied = p[:6]
        txt = p[6] if len(p) > 6 else ''
        D.setdefault(f"{city}|{loc}", []).append(
            {'dt': dt, 'rating': int(rating), 'author': author, 'replied': int(replied), 'txt': txt})
    res = {'_meta': {'source': 'allo_health.external_reviews (Google/GMB, rating<=3) · last ~8 weeks'}}
    for k in sorted(D): res[k] = D[k]
    json.dump(res, open(os.path.join(ROOT, "data_reviews_neg.json"), "w"),
              ensure_ascii=False, separators=(',', ':'))
    print(f"data_reviews_neg.json · {len(D)} clinics with recent negatives")

if __name__ == "__main__":
    main()
