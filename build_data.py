"""
Pull real bookings/leads/done/channel/category data from Redshift and write data.json
sidecar that index.html will fetch().

Run: AWS_PROFILE=redshift-data uv run --with boto3 python build_data.py
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

import boto3

CLUSTER = "warehouse"
DATABASE = "allo_prod"
DAYS = 180


def run_query(client, sql: str) -> tuple[list[str], list[list]]:
    """Execute SQL via Redshift Data API and return (columns, rows)."""
    resp = client.execute_statement(
        ClusterIdentifier=CLUSTER, Database=DATABASE, DbUser="redshift_admin", Sql=sql,
    )
    qid = resp["Id"]
    while True:
        desc = client.describe_statement(Id=qid)
        s = desc["Status"]
        if s == "FINISHED":
            break
        if s in ("FAILED", "ABORTED"):
            raise RuntimeError(f"query failed: {desc.get('Error', s)}")
        time.sleep(0.6)

    cols, rows = [], []
    paginator = client.get_paginator("get_statement_result")
    for page in paginator.paginate(Id=qid):
        if not cols:
            cols = [c["name"] for c in page["ColumnMetadata"]]
        for r in page["Records"]:
            row = []
            for v in r:
                if "isNull" in v and v["isNull"]:
                    row.append(None)
                elif "stringValue" in v:
                    row.append(v["stringValue"])
                elif "longValue" in v:
                    row.append(v["longValue"])
                elif "doubleValue" in v:
                    row.append(v["doubleValue"])
                elif "booleanValue" in v:
                    row.append(v["booleanValue"])
                else:
                    row.append(None)
            rows.append(row)
    return cols, rows


def main():
    session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "redshift-data"))
    client = session.client("redshift-data", region_name="ap-south-1")
    out = {"generated_at": datetime.utcnow().isoformat() + "Z", "lookback_days": DAYS}

    # 1. Clinic metadata
    print("→ Clinic metadata", flush=True)
    cols, rows = run_query(client, """
        SELECT id, name, city, code
        FROM allo_health.locations
        WHERE deleted_at IS NULL AND is_active = 1
        ORDER BY city, name
    """)
    out["clinics"] = [dict(zip(cols, r)) for r in rows]
    print(f"  {len(rows)} clinics", flush=True)

    # 2. Daily bookings + done by clinic — last N days
    print(f"→ Daily bookings by clinic ({DAYS} days)", flush=True)
    cols, rows = run_query(client, f"""
        SELECT
          TO_CHAR(DATE(start_time), 'YYYY-MM-DD') AS d,
          location_id,
          COUNT(*)::int AS bookings,
          SUM(CASE WHEN status='COMPLETED' THEN 1 ELSE 0 END)::int AS done,
          SUM(CASE WHEN status='MISSED' THEN 1 ELSE 0 END)::int AS missed,
          SUM(CASE WHEN status='CANCELLED' THEN 1 ELSE 0 END)::int AS cancelled
        FROM allo_consultations.appointments
        WHERE start_time >= CURRENT_DATE - {DAYS}
          AND start_time < CURRENT_DATE
          AND deleted_at IS NULL
          AND location_id IS NOT NULL
        GROUP BY 1, 2
    """)
    out["bookings"] = [dict(zip(cols, r)) for r in rows]
    print(f"  {len(rows)} clinic-day rows", flush=True)

    # 3. Daily lead attribution: utm_source → counts (channel mix)
    print(f"→ Daily lead attribution ({DAYS} days)", flush=True)
    cols, rows = run_query(client, f"""
        SELECT
          TO_CHAR(DATE(occurred_at), 'YYYY-MM-DD') AS d,
          COALESCE(LOWER(utm_source), 'organic') AS source,
          COUNT(*)::int AS leads
        FROM allo_analytics.lead_attribution_event
        WHERE occurred_at >= CURRENT_DATE - {DAYS}
          AND occurred_at < CURRENT_DATE
          AND deleted_at IS NULL
        GROUP BY 1, 2
    """)
    out["leads"] = [dict(zip(cols, r)) for r in rows]
    print(f"  {len(rows)} day-source rows", flush=True)

    # 4. Daily category mix from diagnosis tags
    print(f"→ Daily category mix ({DAYS} days)", flush=True)
    cols, rows = run_query(client, f"""
        SELECT
          TO_CHAR(DATE(created_at), 'YYYY-MM-DD') AS d,
          tag_type,
          COUNT(*)::int AS n
        FROM allo_analytics.encounter_tags
        WHERE created_at >= CURRENT_DATE - {DAYS}
          AND created_at < CURRENT_DATE
          AND deleted_at IS NULL
          AND tag_category = 'diagnosis'
        GROUP BY 1, 2
    """)
    out["category"] = [dict(zip(cols, r)) for r in rows]
    print(f"  {len(rows)} day-tag rows", flush=True)

    # 5. Ad spend by platform — daily
    print(f"→ Ad spend by platform ({DAYS} days)", flush=True)
    cols, rows = run_query(client, f"""
        SELECT
          TO_CHAR(DATE(report_date), 'YYYY-MM-DD') AS d,
          LOWER(platform) AS platform,
          SUM(spend)::bigint AS spend_paise,
          SUM(impressions)::bigint AS impressions,
          SUM(clicks)::bigint AS clicks,
          SUM(conversions)::bigint AS conversions
        FROM allo_health.ad_platforms_data
        WHERE report_date >= CURRENT_DATE - {DAYS}
          AND report_date < CURRENT_DATE
          AND deleted_at IS NULL
        GROUP BY 1, 2
    """)
    out["spend"] = [dict(zip(cols, r)) for r in rows]
    print(f"  {len(rows)} day-platform rows", flush=True)

    # Write
    path = "/workspace/holistic-demand-dashboard/data.json"
    with open(path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"\n✓ wrote {path} ({os.path.getsize(path):,} bytes)", flush=True)


if __name__ == "__main__":
    main()
