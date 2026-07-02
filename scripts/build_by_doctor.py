#!/usr/bin/env python3
"""Per-clinic × DOCTOR × week cube for booked / done / purchased / revenue — the doctor drill.

booked  = SC by SERVICE week (start_time), deduped per patient/clinic/service-week (COMPLETED-preferred),
          attributed to that SC's provider — so Σ doctors = clinic bottom.booked (service-week basis).
done/purchased/rev = COMPLETED SC by COMPLETION week, deduped per patient/clinic/completion-week,
          attributed to the consult's provider; purchased/rev from that encounter's paid invoices.

Writes clinic['by_doctor'] = {doctor_name: {booked:[52], done:[52], purchased:[52], rev:[52]}}.
Availability-by-doctor is added separately by build_avail_roster.py. One booked + one outcomes query.
Run: AWS_PROFILE=redshift-data python3 scripts/build_by_doctor.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import patch_subcat as PS
ROOT = PS.ROOT; OUT = os.path.join(ROOT, "data_source_recon.json")
idx = PS.idx; Z = PS.Z; LO = PS.LO; run_sql = PS.run_sql

BOOK_SQL = """WITH sc AS (
  SELECT a.id, a.patient_id, pro.name doctor, loc.city ct, loc.locality lc, a.status,
    TO_CHAR(DATE_TRUNC('week', a.start_time + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') wk
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.deleted_at IS NULL AND loc.locality IS NOT NULL AND loc.locality<>''
  JOIN allo_persons.providers pro ON pro.id=a.provider_id AND pro.deleted_at IS NULL
  WHERE a.deleted_at IS NULL AND a.start_time >= '2023-01-01' AND a.start_time < '2026-06-29'),
 dd AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY patient_id, ct, lc, wk
     ORDER BY (CASE WHEN status='COMPLETED' THEN 0 ELSE 1 END), id) rn FROM sc)
SELECT ct, lc, doctor, wk, COUNT(*) booked FROM dd WHERE rn=1 AND wk >= '{lo}' GROUP BY 1,2,3,4;""".format(lo=LO)

OUT_SQL = """WITH inv AS (SELECT e.appointment_id ap_id, SUM(i.amount) amt FROM allo_encounters.encounters e
    JOIN allo_billing.invoices i ON i.encounter_id=e.id AND i.deleted_at IS NULL AND i.status='paid' WHERE e.deleted_at IS NULL GROUP BY 1),
  comp AS (SELECT a.id, pro.name doctor, loc.city ct, loc.locality lc,
      TO_CHAR(DATE_TRUNC('week', COALESCE(a.actual_start_time,a.start_time,a.created_at) + INTERVAL '5 hours 30 minutes'),'YYYY-MM-DD') cwk,
      ROW_NUMBER() OVER (PARTITION BY a.patient_id, loc.city, loc.locality,
        DATE_TRUNC('week', COALESCE(a.actual_start_time,a.start_time,a.created_at) + INTERVAL '5 hours 30 minutes') ORDER BY a.id) rn
    FROM allo_consultations.appointments a
    JOIN allo_consultations.types t ON t.id=a.type_id AND t.name='Screening Call'
    JOIN allo_health.locations loc ON loc.id=a.location_id AND loc.deleted_at IS NULL AND loc.locality IS NOT NULL AND loc.locality<>''
    JOIN allo_persons.providers pro ON pro.id=a.provider_id AND pro.deleted_at IS NULL
    WHERE a.deleted_at IS NULL AND a.status='COMPLETED'
      AND COALESCE(a.actual_start_time,a.start_time,a.created_at) >= '{lo}'
      AND COALESCE(a.actual_start_time,a.start_time,a.created_at) < '2026-06-29')
SELECT c.ct, c.lc, c.doctor, c.cwk, COUNT(*) done,
  SUM(CASE WHEN inv.ap_id IS NOT NULL THEN 1 ELSE 0 END) purchased,
  SUM(CASE WHEN inv.ap_id IS NOT NULL THEN COALESCE(inv.amt,0) ELSE 0 END) rev_paise
FROM comp c LEFT JOIN inv ON inv.ap_id=c.id WHERE c.rn=1 GROUP BY 1,2,3,4;""".format(lo=LO)

def slugify(loc, city):
    s = lambda x: "".join(ch if ch.isalnum() else "_" for ch in (x or "").strip().lower())
    return s(loc) + "_" + s(city)
CITY_ALIAS = {"bengaluru": "bangalore", "gurgaon": "gurugram"}
def norm_city(c): c = (c or "").strip().lower(); return CITY_ALIAS.get(c, c)
FIELDS = ["booked", "done", "purchased", "rev"]

if __name__ == "__main__":
    d = json.load(open(OUT)); clinics = d["clinics"]
    doc = {}   # slug -> doctor -> field -> [weeks]
    def ensure(slug, dr):
        return doc.setdefault(slug, {}).setdefault(dr, {f: Z() for f in FIELDS})
    for line in run_sql(BOOK_SQL):
        r = line.split("\t") if isinstance(line, str) else line
        if len(r) < 5: continue
        ct, lc, dr, wk, bk = r[:5]
        if wk not in idx or not dr: continue
        try: bk = int(float(bk))
        except ValueError: continue
        ensure(slugify(lc, norm_city(ct)), dr)["booked"][idx[wk]] += bk
    for line in run_sql(OUT_SQL):
        r = line.split("\t") if isinstance(line, str) else line
        if len(r) < 7: continue
        ct, lc, dr, cwk, dn, pu, rvp = r[:7]
        if cwk not in idx or not dr: continue
        try: dn = int(float(dn)); pu = int(float(pu)); rv = round(int(float(rvp)) / 100.0)
        except (ValueError, TypeError): continue
        e = ensure(slugify(lc, norm_city(ct)), dr); i = idx[cwk]
        e["done"][i] += dn; e["purchased"][i] += pu; e["rev"][i] += rv

    matched = 0; ndoc = 0
    for slug, c in clinics.items():
        if slug not in doc: continue
        # keep only doctors with any activity; trim all-zero fields to keep JSON lean
        bd = {}
        for dr, fields in doc[slug].items():
            if not any(any(fields[f]) for f in FIELDS): continue
            bd[dr] = {f: fields[f] for f in FIELDS if any(fields[f])}
        if bd:
            c["by_doctor"] = bd; matched += 1; ndoc += len(bd)
    json.dump(d, open(OUT, "w"), separators=(",", ":"))
    print("by_doctor for %d clinics, %d clinic-doctor pairs" % (matched, ndoc))
    am = clinics.get("ameerpet_hyderabad", {}).get("by_doctor", {})
    print("Ameerpet doctors:", len(am))
    for dr in list(am)[:6]:
        print("  %-26s booked6=%s done6=%s" % (dr[:26], am[dr].get("booked", [0])[:6], am[dr].get("done", [0])[:6]))
