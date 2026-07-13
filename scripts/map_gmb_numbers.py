#!/usr/bin/env python3
"""Extend data_gmb_number_clinic.json — attribute GMB inbound-call exophones to their clinic.

The bookings-funnel reads a GMB call's clinic ONLY from the dialed exophone (utm_medium),
matched against data_gmb_number_clinic.json. Exophones missing from that map fall into the
national "no city" bucket. This traces each exophone (lead.utm_medium on inbound_call leads)
→ patient → Screening-Call appointment → clinic, takes the DOMINANT clinic, and adds it to
the map ONLY when the dominant clinic is a confident majority (per-clinic number). Low-share
exophones are genuinely multi-clinic / city-level routers and are LEFT national (reported, not
silently dropped).

Run: AWS_PROFILE=redshift-data python3 scripts/map_gmb_numbers.py            # dry-run report
     AWS_PROFILE=redshift-data python3 scripts/map_gmb_numbers.py --apply    # write the map
"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
MAP = os.path.join(ROOT, "data_gmb_number_clinic.json")
PCT_MIN = 65      # dominant clinic must be >= this share of the exophone's booked patients
TOT_MIN = 10      # and the exophone must have >= this many booked patients (enough signal)

SQL = """
WITH gmb_leads AS (
  SELECT RIGHT(regexp_replace(COALESCE(l.utm_medium,''),'[^0-9]',''),10) AS exo, l.phone_no
  FROM allo_persons.lead l
  WHERE lower(COALESCE(l.utm_campaign,''))='inbound_call' AND l.deleted_at IS NULL
    AND l.created_at >= DATEADD(week,-10,GETDATE())
),
pat_appt AS (
  SELECT g.exo, l2.city||'|'||l2.locality AS clinic, count(distinct p.id) AS n
  FROM gmb_leads g
  JOIN allo_persons.patient p ON p.phone_no=g.phone_no AND p.deleted_at IS NULL
  JOIN allo_consultations.appointments a ON a.patient_id=p.id AND a.deleted_at IS NULL
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.deleted_at IS NULL AND t.name='Screening Call'
  JOIN allo_health.locations l2 ON a.location_id=l2.id AND l2.deleted_at IS NULL AND lower(l2.name) NOT LIKE '%online%'
  GROUP BY 1,2
),
ranked AS (SELECT exo,clinic,n,row_number() over(partition by exo order by n desc) rk, sum(n) over(partition by exo) tot FROM pat_appt)
SELECT exo, clinic, n, tot, round(100.0*n/tot,0) AS pct
FROM ranked WHERE rk=1 AND LENGTH(exo)=10 ORDER BY tot DESC;
"""


def run(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("query failed:\n" + (p.stderr or "")[:800] + "\n"); sys.exit(1)
    return [ln.split("\t") for ln in p.stdout.strip().splitlines() if ln.strip()]


def main():
    apply = "--apply" in sys.argv
    cur = json.load(open(MAP))
    rows = run(SQL)
    add, skip_lowconf, conflict, confirm = {}, [], [], 0
    for exo, clinic, n, tot, pct in rows:
        n, tot, pct = int(n), int(tot), float(pct)
        if exo in cur:
            if cur[exo] != clinic:
                conflict.append((exo, cur[exo], clinic, pct, tot))
            else:
                confirm += 1
            continue
        if (pct >= PCT_MIN and tot >= TOT_MIN) or (pct >= 90 and tot >= 5):   # clear majority w/ volume, OR near-unanimous single-clinic even at low volume
            add[exo] = clinic
        else:
            skip_lowconf.append((exo, clinic, pct, tot))

    print(f"current map: {len(cur)} numbers · query returned {len(rows)} exophones")
    print(f"confirmed existing (same clinic): {confirm}")
    print(f"\nNEW high-confidence (>= {PCT_MIN}% dominant, >= {TOT_MIN} pat) — will ADD {len(add)}:")
    for exo, clinic in sorted(add.items(), key=lambda kv: kv[1]):
        print(f"  {exo}  ->  {clinic}")
    print(f"\nSKIPPED low-confidence (shared / multi-clinic → left NATIONAL) {len(skip_lowconf)}:")
    for exo, clinic, pct, tot in skip_lowconf:
        print(f"  {exo}  ~{clinic} only {pct:.0f}% of {tot} pat")
    if conflict:
        print(f"\n⚠ CONFLICT (map says X, data says Y — NOT changed) {len(conflict)}:")
        for exo, old, new, pct, tot in conflict:
            print(f"  {exo}  map={old}  data={new} ({pct:.0f}% of {tot})")

    if apply and add:
        cur.update(add)
        cur = {k: cur[k] for k in sorted(cur, key=lambda k: cur[k])}
        json.dump(cur, open(MAP, "w"), indent=0, ensure_ascii=False)
        print(f"\n✅ wrote {MAP} — now {len(cur)} numbers (+{len(add)})")
    elif add:
        print(f"\n(dry-run — re-run with --apply to write {len(add)} new mappings)")


if __name__ == "__main__":
    main()
