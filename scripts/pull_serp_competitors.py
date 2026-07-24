#!/usr/bin/env python3
"""Pull top competitors per clinic from allo_analytics.serp_analyses (SERP map-pack).

Unnests parsed_serp.mapPack (case-sensitive SUPER navigation) for sexologist-intent
searches, maps each grid search to its nearest Allo clinic, and aggregates competitor
stats per (clinic, place_id): appearances (grid coverage = threat), avg local-pack
position, rating, reviews, category, nearest distance, sponsorship, and our own
rank/reviews/rating. Writes data_serp_competitors.tsv.

Auth: AWS_PROFILE=redshift-data · cluster warehouse · db allo_prod.
"""
import boto3, os, time, sys

SINCE = '2026-07-10'   # latest full SERP snapshot window
SQL_SELECT = f"""
SELECT CASE WHEN s.keyword ILIKE '%sexologist%' THEN 'SH'
            WHEN s.keyword ILIKE '%std%' OR s.keyword ILIKE '%hiv%' THEN 'STI'
            WHEN s.keyword ILIKE '%psychiatr%' THEN 'MH' END AS cat,
       s.nearest_clinic.city::varchar        AS city,
       s.nearest_clinic.locality::varchar    AS locality,
       s.nearest_clinic.code::varchar        AS code,
       MAX(s.nearest_clinic.reviewsCount::int)       AS our_reviews,
       MAX(s.nearest_clinic.reviewsAvgRating::float) AS our_rating,
       m.placeId::varchar                     AS place_id,
       MAX(m.name::varchar)                   AS comp_name,
       MAX(m.rating::float)                   AS rating,
       MAX(m.reviewsCount::int)               AS reviews,
       MAX(NULLIF(m.category::varchar, ''))   AS category,
       MAX(NULLIF(m.domain::varchar, ''))     AS domain,
       MAX(NULLIF(m.address::varchar, ''))    AS address,
       COUNT(*)                               AS appearances,
       AVG(m.position::float)                 AS avg_pos,
       -- distance from OUR clinic ≈ competitor's distance measured only at grid points within 2km of the clinic
       AVG(CASE WHEN s.nearest_clinic.distanceKm::float <= 2.0 AND m.distance::varchar LIKE '%km%'
                THEN CAST(REGEXP_REPLACE(m.distance::varchar, '[^0-9.]', '') AS float)
                WHEN s.nearest_clinic.distanceKm::float <= 2.0 AND m.distance::varchar LIKE '%m%'
                THEN CAST(REGEXP_REPLACE(m.distance::varchar, '[^0-9.]', '') AS float) / 1000.0
                ELSE NULL END)                 AS clinic_km,
       BOOL_OR(m.isSponsored::boolean)        AS ever_sponsored,
       AVG(s.allo_rank::float)                AS our_avg_rank,
       COUNT(DISTINCT s.id)                   AS clinic_searches
FROM allo_analytics.serp_analyses s, s.parsed_serp.mapPack AS m
WHERE (s.keyword ILIKE '%sexologist%' OR s.keyword ILIKE '%std%' OR s.keyword ILIKE '%hiv%' OR s.keyword ILIKE '%psychiatr%')
  AND s.search_timestamp >= '{SINCE}'
  AND m.name IS NOT NULL
  AND LOWER(m.name::varchar)   NOT LIKE '%allo health%'
  AND LOWER(COALESCE(m.domain::varchar, '')) NOT LIKE '%allohealth%'
GROUP BY 1, 2, 3, 4, m.placeId::varchar
HAVING COUNT(*) >= 3
ORDER BY 1, 2, 3, appearances DESC;
"""
SQLS = ["SET enable_case_sensitive_super_attribute TO true;", SQL_SELECT]


def main():
    cli = boto3.Session(profile_name=os.environ.get("AWS_PROFILE")).client("redshift-data", region_name="ap-south-1")
    rid = cli.batch_execute_statement(ClusterIdentifier="warehouse", Database="allo_prod",
                                      DbUser="redshift_admin", Sqls=SQLS)["Id"]
    while True:
        time.sleep(1.5)
        d = cli.describe_statement(Id=rid)
        if d["Status"] == "FINISHED": break
        if d["Status"] in ("FAILED", "ABORTED"):
            sys.stderr.write("FAIL: " + str(d.get("Error")) + "\n"); sys.exit(1)
    sub = d["SubStatements"][-1]["Id"]   # the SELECT result
    cols = None; rows = []; tok = None
    while True:
        kw = dict(Id=sub)
        if tok: kw["NextToken"] = tok
        p = cli.get_statement_result(**kw)
        if cols is None: cols = [c["name"] for c in p["ColumnMetadata"]]
        for r in p["Records"]:
            rows.append(["" if (not c or c.get("isNull")) else list(c.values())[0] for c in r])
        tok = p.get("NextToken")
        if not tok: break
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_serp_competitors.tsv")
    with open(out, "w") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows: f.write("\t".join(str(v) for v in r) + "\n")
    print(f"wrote {out} · {len(rows)} clinic-competitor rows")


if __name__ == "__main__":
    main()
