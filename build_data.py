"""
Pull real bookings / leads / done / channel / category / spend data from Redshift
and write data.json that index.html fetches at load.

Run: AWS_PROFILE=redshift-data uv run --with boto3 python build_data.py
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime

import boto3

CLUSTER = "warehouse"
DATABASE = "allo_prod"
DAYS = 180

# Canonicalized utm_source → ~15 buckets. Used in 3 queries; keep in one place.
SOURCE_CASE = """
  CASE
    WHEN {col} IS NULL THEN 'organic'
    WHEN LOWER({col}) LIKE 'gmb%' THEN 'gmb'
    WHEN LOWER({col}) LIKE 'fb%' THEN 'fb'
    WHEN LOWER({col}) LIKE 'ig%' THEN 'ig'
    WHEN LOWER({col}) LIKE 'google%' THEN 'google'
    WHEN LOWER({col}) LIKE 'organic%' THEN 'organic'
    WHEN LOWER({col}) LIKE 'practo%' THEN 'practo'
    WHEN LOWER({col}) LIKE 'directwalkin%' THEN 'directwalkin'
    WHEN LOWER({col}) LIKE 'justdial%' THEN 'justdial'
    WHEN LOWER({col}) LIKE 'vcard%' THEN 'vcard'
    WHEN LOWER({col}) LIKE 'youtube%' OR LOWER({col}) = 'yt' THEN 'youtube'
    WHEN LOWER({col}) LIKE 'googlelisting%' THEN 'googlelisting'
    WHEN LOWER({col}) LIKE 'chatgpt%' THEN 'chatgpt'
    WHEN LOWER({col}) LIKE 'perplexity%' THEN 'perplexity'
    WHEN LOWER({col}) LIKE 'doctorreferral%'
         OR LOWER({col}) LIKE 'allo%refer%' THEN 'referral'
    ELSE 'other'
  END
"""


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
        SELECT id, name, city, code, created_at
        FROM allo_health.locations
        WHERE deleted_at IS NULL AND is_active = 1
        ORDER BY city, name
    """)
    out["clinics"] = [dict(zip(cols, r)) for r in rows]
    print(f"  {len(rows)} clinics", flush=True)

    # 2. Daily bookings / done / missed / cancelled by clinic.
    # Truth volume — counted from appointments directly, no joins, no fan-out.
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

    # 3. Daily unique leads by source — network-wide (no clinic dim).
    # Counts allo_persons.lead which matches the L0 sheet (5,887 vs sheet's 5,899
    # for wk May 11–17). Previously used lead_attribution_event which was ~13× too high.
    print(f"→ Daily leads by source ({DAYS} days)", flush=True)
    src = SOURCE_CASE.format(col="utm_source")
    cols, rows = run_query(client, f"""
        SELECT
          TO_CHAR(DATE(created_at), 'YYYY-MM-DD') AS d,
          {src} AS source,
          COUNT(*)::int AS leads
        FROM allo_persons.lead
        WHERE created_at >= CURRENT_DATE - {DAYS}
          AND created_at < CURRENT_DATE
          AND deleted_at IS NULL
        GROUP BY 1, 2
    """)
    out["leads"] = [dict(zip(cols, r)) for r in rows]
    print(f"  {len(rows)} day-source rows", flush=True)

    # 4. NEW — per-clinic lead attribution via first-appointment join.
    # A lead's "clinic" = location_id of its earliest non-deleted appointment.
    # Leads with no appointment → location_id is NULL (unattributed bucket).
    print(f"→ Daily leads by clinic+source ({DAYS} days)", flush=True)
    src_l = SOURCE_CASE.format(col="l.utm_source")
    cols, rows = run_query(client, f"""
        WITH first_appt AS (
          SELECT
            p.lead_id,
            MIN(a.start_time) AS first_appt_at
          FROM allo_persons.patient p
          JOIN allo_consultations.appointments a
            ON a.patient_id = p.id
           AND a.deleted_at IS NULL
           AND a.location_id IS NOT NULL
          WHERE p.deleted_at IS NULL
            AND p.lead_id IS NOT NULL
          GROUP BY 1
        ),
        first_loc AS (
          SELECT
            fa.lead_id,
            a.location_id AS first_location_id
          FROM first_appt fa
          JOIN allo_persons.patient p
            ON p.lead_id = fa.lead_id AND p.deleted_at IS NULL
          JOIN allo_consultations.appointments a
            ON a.patient_id = p.id
           AND a.start_time = fa.first_appt_at
           AND a.deleted_at IS NULL
           AND a.location_id IS NOT NULL
        )
        SELECT
          TO_CHAR(DATE(l.created_at), 'YYYY-MM-DD') AS d,
          fl.first_location_id AS location_id,
          {src_l} AS source,
          COUNT(*)::int AS leads
        FROM allo_persons.lead l
        LEFT JOIN first_loc fl ON fl.lead_id = l.id
        WHERE l.created_at >= CURRENT_DATE - {DAYS}
          AND l.created_at < CURRENT_DATE
          AND l.deleted_at IS NULL
        GROUP BY 1, 2, 3
    """)
    out["leads_by_clinic"] = [dict(zip(cols, r)) for r in rows]
    print(f"  {len(rows)} day-clinic-source rows", flush=True)

    # 5. Clinic × Source × Diagnosis — FIXED to avoid both fan-out and coverage loss.
    # Old query: INNER JOIN encounter_tags → dropped ~50% of completed appts that had no tag.
    #            Also fanned out across multiple tags per encounter.
    # New query: LEFT JOIN encounter-level aggregate. One row per appointment. Diagnosis
    # tags become booleans (has_sti, has_sh, has_others). Then:
    #   tagged_done = SUM(CASE WHEN tag_count > 0 THEN 1 END)  → measures coverage
    #   sti_done    = SUM(has_sti)                              → counted once per encounter
    #   total_done  = COUNT(*)                                  → matches bookings.done
    print(f"→ Clinic × Source × Diagnosis ({DAYS} days)", flush=True)
    src_a = SOURCE_CASE.format(col="l.utm_source")
    cols, rows = run_query(client, f"""
        WITH enc_tags AS (
          SELECT
            e.appointment_id,
            MAX(CASE WHEN et.tag_type = 'sti' THEN 1 ELSE 0 END) AS has_sti,
            MAX(CASE
                  WHEN et.tag_type IN ('ed_plus','pe_plus','ed_plus_pe_plus') THEN 1
                  ELSE 0
                END) AS has_sh,
            MAX(CASE WHEN et.tag_type = 'others' THEN 1 ELSE 0 END) AS has_others,
            COUNT(et.id) AS tag_count
          FROM allo_encounters.encounters e
          LEFT JOIN allo_analytics.encounter_tags et
            ON et.encounter_id = e.id
           AND et.tag_category = 'diagnosis'
           AND et.deleted_at IS NULL
          WHERE e.deleted_at IS NULL
          GROUP BY 1
        )
        SELECT
          TO_CHAR(DATE(a.start_time), 'YYYY-MM-DD') AS d,
          a.location_id,
          {src_a} AS source,
          COUNT(*)::int AS total_done,
          SUM(CASE WHEN COALESCE(et.tag_count, 0) > 0 THEN 1 ELSE 0 END)::int AS tagged_done,
          SUM(COALESCE(et.has_sti,    0))::int AS sti_done,
          SUM(COALESCE(et.has_sh,     0))::int AS sh_done,
          SUM(COALESCE(et.has_others, 0))::int AS others_done
        FROM allo_consultations.appointments a
        LEFT JOIN enc_tags et ON et.appointment_id = a.id
        LEFT JOIN allo_persons.patient p
          ON p.id = a.patient_id AND p.deleted_at IS NULL
        LEFT JOIN allo_persons.lead l
          ON l.id = p.lead_id AND l.deleted_at IS NULL
        WHERE a.start_time >= CURRENT_DATE - {DAYS}
          AND a.start_time < CURRENT_DATE
          AND a.deleted_at IS NULL
          AND a.location_id IS NOT NULL
          AND a.status = 'COMPLETED'
        GROUP BY 1, 2, 3
    """)
    out["clinic_source_diagnosis"] = [dict(zip(cols, r)) for r in rows]
    print(f"  {len(rows)} day-clinic-source rows", flush=True)

    # 6. Daily network category mix (kept for backward compat; dashboard prefers #5).
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

    # 7. Ad spend by platform — daily
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
