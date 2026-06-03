"""
fetch_bookings.py — Pull Screening-Call bookings from Redshift in the **sheet's
exact logic** and write /tmp/bookings_full.csv for rebuild_data.py.

Validated to reconcile to the tracker sheet (W6 25-31 May 2026): total 1,652,
online 465 / offline 1,187, Practo 201, channels GMB/Google/FB within ~3%.

Sheet logic encoded here:
  - one row per SC appointment, with `phone_rank` = ROW_NUMBER() over the
    patient's PHONE ordered by created_at (ranked over FULL history from 2023,
    so repeat patients are correctly identified). Bookings = phone_rank == 1.
  - `apt_create_dt` = booking *created* date (the sheet buckets bookings by this).
  - `apt_status_final` for Calls Done (= COMPLETED by schedule date — unfiltered by rank).
  - online/offline via consultation `mode` ('online' => locality 'Online').
  - `Source final` channel = phone-Practo-match (CSV) → utm/origin waterfall.

Run:  AWS_PROFILE=redshift-data python3 fetch_bookings.py [--practo-csv PATH]
Then: python3 rebuild_data.py
"""
from __future__ import annotations
import argparse, csv, os, sys, time
import boto3

CLUSTER, DATABASE, DB_USER, REGION = "warehouse", "allo_prod", "redshift_admin", "ap-south-1"
OUT_CSV = "/tmp/bookings_full.csv"
OUT_DAYS = 200          # rows to emit (ranking still uses full history)
RANK_FLOOR = "2023-01-01"

COLS = ["apt_schedule_dt", "apt_create_dt", "apt_status_final", "phone_rank",
        "Source final", "diag_cat", "city", "locality", "mode"]


def run_query(client, sql):
    qid = client.execute_statement(ClusterIdentifier=CLUSTER, Database=DATABASE, DbUser=DB_USER, Sql=sql)["Id"]
    while True:
        time.sleep(2); d = client.describe_statement(Id=qid)
        if d["Status"] == "FINISHED": break
        if d["Status"] in ("FAILED", "ABORTED"): sys.exit(f"Query failed: {d.get('Error')}")
    rows, tok = [], None
    while True:
        kw = dict(Id=qid)
        if tok: kw["NextToken"] = tok
        page = client.get_statement_result(**kw)
        cols = [c["name"] for c in page["ColumnMetadata"]]
        for r in page["Records"]:
            rows.append([(list(c.values())[0] if c else None) for c in r])
        tok = page.get("NextToken")
        if not tok: break
    return cols, rows


SQL = f"""
WITH sc AS (
  SELECT a.id, a.created_at, a.start_time, a.status, a.location_id, c.mode, p.phone_no, c.patient_id,
         ROW_NUMBER() OVER (PARTITION BY p.phone_no ORDER BY a.created_at, a.id) AS phone_rank
  FROM allo_consultations.appointments a
    JOIN allo_consultations.consultations c ON a.consultation_id = c.id
    JOIN allo_persons.patient p ON c.patient_id = p.id
  WHERE a.deleted_at IS NULL AND c.deleted_at IS NULL AND p.phone_no IS NOT NULL
    AND c.consultation_type_id = (SELECT id FROM allo_consultations.types WHERE name='Screening Call')
    AND a.created_at >= '{RANK_FLOOR}'
),
diag AS (
  SELECT e.appointment_id,
    CASE WHEN MAX(CASE WHEN et.tag_type='sti' THEN 1 ELSE 0 END)=1 THEN 'STI'
         WHEN MAX(CASE WHEN et.tag_type='ed_plus_pe_plus' THEN 1 ELSE 0 END)=1 THEN 'ED+PE+'
         WHEN MAX(CASE WHEN et.tag_type='ed_plus' THEN 1 ELSE 0 END)=1 THEN 'ED+'
         WHEN MAX(CASE WHEN et.tag_type='pe_plus' THEN 1 ELSE 0 END)=1 THEN 'PE+'
         WHEN MAX(CASE WHEN et.tag_type='nssd' THEN 1 ELSE 0 END)=1 THEN 'NSSD' ELSE 'oth' END AS diag_cat
  FROM allo_encounters.encounters e
  LEFT JOIN allo_analytics.encounter_tags et ON et.encounter_id=e.id AND et.tag_category='diagnosis' AND et.deleted_at IS NULL
  WHERE e.deleted_at IS NULL GROUP BY 1
),
mh AS (
  -- Mental Health = doctor's clinical paperform flag isMHOrSH='MH Only' (field exists from 2026-04-23).
  -- Validated against the manual MH dashboard: 113/114 match (99%) once the field exists.
  SELECT e.appointment_id, MAX(CASE WHEN q.value='MH Only' THEN 1 ELSE 0 END) AS mh_only
  FROM allo_encounters.encounters e
  JOIN allo_health.paperform_qa q ON q.encounter_id=e.id AND q.custom_key='isMHOrSH' AND q.deleted_at IS NULL
  WHERE e.deleted_at IS NULL GROUP BY 1
)
SELECT TO_CHAR(DATE(sc.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS apt_schedule_dt,
       TO_CHAR(DATE(sc.created_at  + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS apt_create_dt,
       sc.status AS apt_status_final, sc.phone_rank,
       sc.phone_no, LOWER(COALESCE(ld.utm_source,'')) utm_source, LOWER(COALESCE(ld.origin,'')) origin,
       CASE WHEN mh.mh_only=1 THEN 'MH' ELSE COALESCE(d.diag_cat,'oth') END AS diag_cat,
       COALESCE(loc.city,'') city,
       COALESCE(loc.locality, loc.name,'') locality, COALESCE(sc.mode,'') AS consult_mode
FROM sc
  LEFT JOIN allo_health.locations loc ON loc.id=sc.location_id AND loc.deleted_at IS NULL
  LEFT JOIN allo_persons.patient pt ON pt.id=sc.patient_id
  LEFT JOIN allo_persons.lead ld ON ld.id=pt.lead_id AND ld.deleted_at IS NULL
  LEFT JOIN diag d ON d.appointment_id=sc.id
  LEFT JOIN mh ON mh.appointment_id=sc.id
WHERE sc.created_at >= CURRENT_DATE - {OUT_DAYS}
"""


def load_practo(path):
    phones = set()
    if path and os.path.exists(path):
        for r in csv.DictReader(open(path)):
            m = (r.get("mob_no") or "").strip()
            if len(m) == 10 and m.isdigit():
                phones.add("+91" + m)
    else:
        print(f"  ! Practo CSV not found ({path}); Practo channel will be under-counted.")
    return phones


def source_final(phone, utm, origin, practo):
    """Replicates the sheet's `Source final` waterfall (Practo > FB > Google > GMB > Organic > Other)."""
    if phone in practo: return "Practo"
    if utm in ("fb", "ig", "instagram", "facebook", "meta"): return "FB"
    if utm in ("google", "google_ads"): return "Google"
    if utm in ("gmb", "google_my_business", "googlelisting", "directwalkin", "walkin"): return "GMB"
    if any(k in origin for k in ("google listing", "pc-inbound", "walk in", "gmb")): return "GMB"
    if utm == "organic" or any(k in origin for k in ("organic", "whatsapp", "inbound")): return "Organic"
    if utm == "practo": return "Practo"
    return "Other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--practo-csv", default=os.path.expanduser("~/Downloads/Flow Dashboard view - Sheet37 (1).csv"))
    a = ap.parse_args()
    client = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "redshift-data")).client("redshift-data", region_name=REGION)
    practo = load_practo(a.practo_csv)
    print(f"→ Pulling SC bookings (sheet logic, phone_rank over history)…  Practo phones: {len(practo)}")
    cols, rows = run_query(client, SQL)
    idx = {c: i for i, c in enumerate(cols)}
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.writer(f); w.writerow(COLS)
        for r in rows:
            phone = str(r[idx["phone_no"]] or ""); utm = str(r[idx["utm_source"]] or ""); og = str(r[idx["origin"]] or "")
            ch = source_final(phone, utm, og, practo)
            w.writerow([r[idx["apt_schedule_dt"]], r[idx["apt_create_dt"]], r[idx["apt_status_final"]],
                        r[idx["phone_rank"]], ch, r[idx["diag_cat"]], r[idx["city"]], r[idx["locality"]], r[idx["consult_mode"]]])
    print(f"✓ Wrote {OUT_CSV} ({len(rows):,} rows). Bookings = rows where phone_rank=1, bucketed by apt_create_dt.")
    print("Next: python3 rebuild_data.py")


if __name__ == "__main__":
    main()
