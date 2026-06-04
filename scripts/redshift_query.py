#!/usr/bin/env python3
"""Run a GAQL-style Redshift query (read from stdin) and print TSV rows. Used by the build scripts.
Auth: AWS_PROFILE=redshift-data (SSO) · cluster 'warehouse' · db allo_prod · region ap-south-1.
Usage:  python3 scripts/redshift_query.py < query.sql"""
import boto3, os, time, sys

def run(sql):
    cli = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "redshift-data")) \
              .client("redshift-data", region_name="ap-south-1")
    qid = cli.execute_statement(ClusterIdentifier="warehouse", Database="allo_prod",
                                DbUser="redshift_admin", Sql=sql)["Id"]
    while True:
        time.sleep(1.3)
        d = cli.describe_statement(Id=qid)
        if d["Status"] == "FINISHED":
            break
        if d["Status"] in ("FAILED", "ABORTED"):
            sys.stderr.write("FAIL: " + str(d.get("Error")) + "\n")
            return None
    rows, tok = [], None
    while True:
        kw = dict(Id=qid)
        if tok:
            kw["NextToken"] = tok
        p = cli.get_statement_result(**kw)
        for r in p["Records"]:
            rows.append([list(c.values())[0] if c else None for c in r])
        tok = p.get("NextToken")
        if not tok:
            break
    return rows

if __name__ == "__main__":
    for row in (run(sys.stdin.read()) or []):
        print("\t".join("" if v is None else str(v) for v in row))
