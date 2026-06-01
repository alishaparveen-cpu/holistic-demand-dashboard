"""
fetch_bookings.py — Pull appointment data from Redshift and write
/tmp/bookings_full.csv in the format expected by rebuild_data.py.

Run:
    AWS_PROFILE=redshift-data python3 fetch_bookings.py
Then:
    python3 rebuild_data.py
"""

from __future__ import annotations

import csv
import os
import sys
import time

import boto3

CLUSTER  = "warehouse"
DATABASE = "allo_prod"
DB_USER  = "redshift_admin"
REGION   = "ap-south-1"
DAYS     = 200   # pull enough history to cover 12 complete weeks + buffer
OUT_CSV  = "/tmp/bookings_full.csv"

COLS = [
    "apt_schedule_dt",
    "apt_create_dt",
    "apt_status_final",
    "Source final",
    "diag_cat",
    "city",
    "locality",
    "offline_location_flag",
]


def run_query(client, sql: str):
    """Execute SQL via Redshift Data API; return (col_names, rows)."""
    resp = client.execute_statement(
        ClusterIdentifier=CLUSTER,
        Database=DATABASE,
        DbUser=DB_USER,
        Sql=sql,
    )
    qid = resp["Id"]
    print(f"  query id={qid}", end="", flush=True)
    while True:
        time.sleep(2)
        desc = client.describe_statement(Id=qid)
        st = desc["Status"]
        if st == "FINISHED":
            print(f"  ✓ {desc['ResultRows']} rows", flush=True)
            break
        if st in ("FAILED", "ABORTED"):
            print(f"\n  ✗ {desc.get('Error','')}", flush=True)
            sys.exit(1)
        print(".", end="", flush=True)

    rows, token = [], None
    while True:
        kwargs = dict(Id=qid)
        if token:
            kwargs["NextToken"] = token
        page = client.get_statement_result(**kwargs)
        cols = [c["name"] for c in page["ColumnMetadata"]]
        for r in page["Records"]:
            rows.append([
                (list(cell.values())[0] if cell else None) for cell in r
            ])
        token = page.get("NextToken")
        if not token:
            break
    return cols, rows


SQL = f"""
WITH diag AS (
  SELECT
    e.appointment_id,
    CASE
      WHEN MAX(CASE WHEN et.tag_type = 'sti'          THEN 1 ELSE 0 END) = 1 THEN 'STI'
      WHEN MAX(CASE WHEN et.tag_type = 'ed_plus_pe_plus' THEN 1 ELSE 0 END) = 1 THEN 'ED+PE+'
      WHEN MAX(CASE WHEN et.tag_type = 'ed_plus'      THEN 1 ELSE 0 END) = 1 THEN 'ED+'
      WHEN MAX(CASE WHEN et.tag_type = 'pe_plus'      THEN 1 ELSE 0 END) = 1 THEN 'PE+'
      WHEN MAX(CASE WHEN et.tag_type = 'nssd'         THEN 1 ELSE 0 END) = 1 THEN 'NSSD'
      ELSE 'oth'
    END AS diag_cat
  FROM allo_encounters.encounters e
  LEFT JOIN allo_analytics.encounter_tags et
    ON et.encounter_id = e.id
   AND et.tag_category = 'diagnosis'
   AND et.deleted_at IS NULL
  WHERE e.deleted_at IS NULL
  GROUP BY 1
)
SELECT
  TO_CHAR(DATE(a.start_time),   'YYYY-MM-DD') AS apt_schedule_dt,
  TO_CHAR(DATE(a.created_at),   'YYYY-MM-DD') AS apt_create_dt,
  CASE a.status
    WHEN 'MISSED' THEN 'NO_SHOW'
    ELSE a.status
  END                                          AS apt_status_final,
  COALESCE(l.utm_source, 'organic')            AS "Source final",
  COALESCE(d.diag_cat, 'oth')                  AS diag_cat,
  COALESCE(loc.city, '')                       AS city,
  COALESCE(loc.locality, loc.name, '')         AS locality,
  '1'                                          AS offline_location_flag
FROM allo_consultations.appointments a
JOIN allo_health.locations loc
  ON loc.id = a.location_id
 AND loc.deleted_at IS NULL
 AND loc.is_active = 1
LEFT JOIN allo_persons.patient p
  ON p.id = a.patient_id AND p.deleted_at IS NULL
LEFT JOIN allo_persons.lead l
  ON l.id = p.lead_id AND l.deleted_at IS NULL
LEFT JOIN diag d ON d.appointment_id = a.id
WHERE a.start_time >= CURRENT_DATE - {DAYS}
  AND a.start_time  < CURRENT_DATE
  AND a.deleted_at IS NULL
  AND a.location_id IS NOT NULL
  AND a.status IN ('COMPLETED', 'MISSED', 'RESCHEDULED', 'NO_SHOW', 'CANCELLED')
"""


def main():
    profile = os.environ.get("AWS_PROFILE", "redshift-data")
    print(f"Using AWS profile: {profile}")
    session = boto3.Session(profile_name=profile)
    client  = session.client("redshift-data", region_name=REGION)

    print(f"→ Pulling appointments from Redshift ({DAYS}-day window)…")
    cols, rows = run_query(client, SQL)

    print(f"→ Writing {OUT_CSV}…")
    with open(OUT_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLS)   # fixed header expected by rebuild_data.py
        col_idx = {c: i for i, c in enumerate(cols)}
        for row in rows:
            writer.writerow([row[col_idx[c]] for c in COLS])

    size_mb = os.path.getsize(OUT_CSV) / 1_048_576
    print(f"✓ Wrote {OUT_CSV} ({len(rows):,} rows, {size_mb:.1f} MB)")
    print("\nNext: python3 rebuild_data.py")


if __name__ == "__main__":
    main()
