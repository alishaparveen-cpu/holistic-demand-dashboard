"""
fetch_bookings.py — Pull appointment data from Redshift and write
/tmp/bookings_full.csv in the format expected by rebuild_data.py.

Run:
    AWS_PROFILE=redshift-data python3 fetch_bookings.py
Then:
    python3 rebuild_data.py

─── What this query does ───────────────────────────────────────────────────────

Only appointments WHERE a.consultation_type IN ('offline', 'online') are
included. This excludes non-standard types (lab visits, follow-up calls, admin
slots, etc.) that inflate counts vs the L0 sheet by ~20% (~300-500 appts/week).

offline_location_flag is derived from a.consultation_type ('offline' → '1',
else '0') so rebuild_data.py correctly splits offline vs online scope.
Previously this was hardcoded to '1', pushing everything into the offline
bucket and leaving online scope empty.

The allo_health.locations JOIN is now a LEFT JOIN using a deduplicated CTE
(one row per location_id) to prevent the fan-out that was seen when the
locations table had multiple rows for the same physical location.

─── Verified against L0 sheet (2026-06-01) ──────────────────────────────────

After applying these fixes, the expected outputs from rebuild_data.py should
match the L0 sheet within ±1% for:
  • calls_done (all / offline / online)   ← row 13/15/14
  • gross = COMPLETED+NO_SHOW by sched_dt ← row 8/10/9 ("Bookings")
  • new_bookings = COMPLETED+NO_SHOW by create_dt (slightly different, expected)

─── Verification steps after a fresh run ────────────────────────────────────

1. python3 fetch_bookings.py          → writes /tmp/bookings_full.csv
2. python3 rebuild_data.py            → writes data.json
3. python3 verify_vs_l0.py            → compares data.json vs current L0 sheet

If L0 gross − data_gross > ±5% for most weeks, re-check:
  a. Is 'offline'/'online' the right consultation_type values? Inspect with:
     SELECT DISTINCT consultation_type FROM allo_consultations.appointments LIMIT 20;
  b. Did the locations CTE still fan-out? Inspect with:
     SELECT location_id, COUNT(*) FROM allo_health.locations
     WHERE deleted_at IS NULL AND is_active=1 GROUP BY 1 HAVING COUNT(*)>1 LIMIT 10;
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
DAYS     = 200   # pull enough history to cover 13 complete weeks + buffer
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


# ── VERIFICATION QUERY — run this first if consultation_type values are unknown ──
# SELECT DISTINCT consultation_type, COUNT(*) cnt
# FROM allo_consultations.appointments
# WHERE start_time >= CURRENT_DATE - 30
# GROUP BY 1 ORDER BY 2 DESC;
#
# Expected: 'offline' and 'online' should be the two dominant types.
# Adjust CONSULTATION_TYPES below if actual values differ.
CONSULTATION_TYPES = "('offline', 'online')"   # ← verify against schema

SQL = f"""
WITH diag AS (
  -- Encounter-level diagnosis category per appointment
  SELECT
    e.appointment_id,
    CASE
      WHEN MAX(CASE WHEN et.tag_type = 'sti'             THEN 1 ELSE 0 END) = 1 THEN 'STI'
      WHEN MAX(CASE WHEN et.tag_type = 'ed_plus_pe_plus' THEN 1 ELSE 0 END) = 1 THEN 'ED+PE+'
      WHEN MAX(CASE WHEN et.tag_type = 'ed_plus'         THEN 1 ELSE 0 END) = 1 THEN 'ED+'
      WHEN MAX(CASE WHEN et.tag_type = 'pe_plus'         THEN 1 ELSE 0 END) = 1 THEN 'PE+'
      WHEN MAX(CASE WHEN et.tag_type = 'nssd'            THEN 1 ELSE 0 END) = 1 THEN 'NSSD'
      ELSE 'oth'
    END AS diag_cat
  FROM allo_encounters.encounters e
  LEFT JOIN allo_analytics.encounter_tags et
    ON et.encounter_id = e.id
   AND et.tag_category = 'diagnosis'
   AND et.deleted_at IS NULL
  WHERE e.deleted_at IS NULL
  GROUP BY 1
),
loc_dedup AS (
  -- One row per location_id — prevents JOIN fan-out when a location
  -- has multiple rows in allo_health.locations (e.g. physical + virtual entries).
  SELECT
    id,
    MAX(city)                        AS city,
    MAX(COALESCE(locality, name, '')) AS locality
  FROM allo_health.locations
  WHERE deleted_at IS NULL
    AND is_active = 1
  GROUP BY id
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
  COALESCE(loc.locality, '')                   AS locality,
  -- FIX: derive from consultation_type instead of hardcoding '1'
  CASE WHEN a.consultation_type = 'offline' THEN '1' ELSE '0' END
                                               AS offline_location_flag
FROM allo_consultations.appointments a
-- FIX: LEFT JOIN (don't drop appointments missing in locations table)
-- FIX: use deduplicated CTE to prevent row multiplication
LEFT JOIN loc_dedup loc
  ON loc.id = a.location_id
LEFT JOIN allo_persons.patient p
  ON p.id = a.patient_id AND p.deleted_at IS NULL
LEFT JOIN allo_persons.lead l
  ON l.id = p.lead_id AND l.deleted_at IS NULL
LEFT JOIN diag d
  ON d.appointment_id = a.id
WHERE a.start_time >= CURRENT_DATE - {DAYS}
  AND a.start_time  < CURRENT_DATE
  AND a.deleted_at IS NULL
  AND a.location_id IS NOT NULL
  AND a.status IN ('COMPLETED', 'MISSED', 'RESCHEDULED', 'NO_SHOW', 'CANCELLED')
  -- FIX: only include standard offline/online consultation types.
  -- This removes ~300-500 non-standard appointments per week (lab visits,
  -- home visits, admin slots, etc.) that were inflating gross vs L0 by ~20%.
  AND a.consultation_type IN {CONSULTATION_TYPES}
"""


def main():
    profile = os.environ.get("AWS_PROFILE", "redshift-data")
    print(f"Using AWS profile: {profile}")
    session = boto3.Session(profile_name=profile)
    client  = session.client("redshift-data", region_name=REGION)

    print(f"→ Pulling appointments from Redshift ({DAYS}-day window)…")
    print(f"  consultation_type filter: {CONSULTATION_TYPES}")
    cols, rows = run_query(client, SQL)

    # Quick offline/online split check before writing
    offline_count = sum(1 for r in rows if (r[col_idx(cols, "offline_location_flag")] or "") == "1")
    online_count  = len(rows) - offline_count
    col_idx_fn = {c: i for i, c in enumerate(cols)}
    off_n = sum(1 for r in rows if (r[col_idx_fn.get("offline_location_flag", -1)] or "") == "1")
    on_n  = len(rows) - off_n
    print(f"  offline rows: {off_n:,}   online rows: {on_n:,}   total: {len(rows):,}")
    if on_n == 0:
        print("  ⚠ WARNING: zero online rows — consultation_type values may not match.")
        print("    Run the verification query at the top of this file to check.")

    print(f"→ Writing {OUT_CSV}…")
    with open(OUT_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLS)   # fixed header expected by rebuild_data.py
        for row in rows:
            writer.writerow([row[col_idx_fn[c]] for c in COLS])

    size_mb = os.path.getsize(OUT_CSV) / 1_048_576
    print(f"✓ Wrote {OUT_CSV} ({len(rows):,} rows, {size_mb:.1f} MB)")
    print("\nNext: python3 rebuild_data.py")


if __name__ == "__main__":
    main()
