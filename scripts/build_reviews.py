#!/usr/bin/env python3
"""Build data_reviews.json — per-clinic weekly GMB review velocity for the diagnostic
(review velocity + rating + negative-review count). Source: allo_health.external_reviews
(platform google/gmb) via fetch_reviews.sql.

Per "City|Clinic" (newest-first, 12 weeks):
  n      [12]  reviews received that week (velocity — a primary GMB-rank driver)
  rating [12]  avg star rating that week, or None when no reviews
  neg    [12]  reviews with rating <= 3 that week

NOTE: builder lost in a re-clone (only fetch_reviews.sql was committed); rebuilt 2026-06-15.
Run:  AWS_PROFILE=redshift-data python3 scripts/build_reviews.py
"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ   = os.path.join(ROOT, "scripts", "redshift_query.py")
WEEKS = ["2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04",
         "2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23"]
idx = {w: i for i, w in enumerate(WEEKS)}
NW = len(WEEKS)


def main():
    sql = open(os.path.join(ROOT, "scripts", "fetch_reviews.sql")).read()
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("fetch_reviews failed: " + (p.stderr or "")[:400] + "\n"); sys.exit(1)
    D = {}
    for line in p.stdout.strip().splitlines():
        c = line.split("\t")
        if len(c) < 6: continue
        city, loc, wk, n, rating, neg = c[:6]
        if wk not in idx or not loc: continue
        o = D.setdefault(f"{city}|{loc}", {"n":[0]*NW, "rating":[None]*NW, "neg":[0]*NW})
        i = idx[wk]
        try: o["n"][i] = int(float(n))
        except ValueError: pass
        try: o["rating"][i] = round(float(rating), 2)
        except (ValueError, TypeError): pass
        try: o["neg"][i] = int(float(neg))
        except ValueError: pass
    out = dict(D)
    out["_meta"] = {"weeks": WEEKS, "source": "allo_health.external_reviews (platform google/gmb) — offline clinics, IST weeks"}
    json.dump(out, open(os.path.join(ROOT, "data_reviews.json"), "w"), separators=(",", ":"))
    tot = sum(sum(o["n"]) for o in D.values())
    print(f"data_reviews.json · {len(D)} clinics · {tot} reviews over {WEEKS[-1]}→{WEEKS[0]}")


if __name__ == "__main__":
    main()
