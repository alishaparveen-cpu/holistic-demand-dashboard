#!/usr/bin/env python3
"""Build data_sc_bookings_online.json — SC-ONLINE booking funnel (telehealth), mirror of the offline SC cube.

  - Screening Call ONLINE = apt.location_id IN (2 telehealth UUIDs) (loc.name LIKE '%online%')
  - EXACT per-clinic attribution: each online appt is credited to the DOCTOR'S BLOCK LOCATION that day
    (join doctor_location on provider_id + block_dt + block_id → COALESCE(city,'Online')). Matches the
    canonical org query. Keyed by 'city|locality' like offline; unresolved blocks → 'Online|Online'.

Per 'city|locality' × week: booked / done / ft_same / ft_prev / ft_nolead / repeat / ret_return / ret_rebook (+ by_doctor / by_source)
Run: AWS_PROFILE=redshift-data python3 scripts/build_sc_bookings_online.py
"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
START_WK = "2025-07-01"
TELE = "'c7d8c9d2-f389-4e8f-a260-71110195b83f','ffe8d849-3099-48fe-a2df-e324c4befe56'"   # the 2 telehealth location UUIDs = ONLINE (matches the sheet's RD-Pat-level definition; name-match undercounted)

SQL = f"""
WITH doctor_location AS (
  SELECT DISTINCT DATE(ab.start_time + INTERVAL '5.5 hours') AS block_dt, ab.id AS block_id, ab.provider_id, loc.city, loc.locality
  FROM allo_consultations.appointment_block_type_maps abtm
  LEFT JOIN allo_consultations.appointment_blocks ab ON abtm.appointment_block_id=ab.id
  LEFT JOIN allo_health.locations loc ON abtm.offline_location_id=loc.id AND loc.deleted_at IS NULL
  WHERE abtm.deleted_at IS NULL AND ab.deleted_at IS NULL AND abtm.offline_location_id IS NOT NULL
),
paperform_qa AS (   -- patient's most-recent merged-Rx diagnosis → category (same rollup as the offline econ builder)
  SELECT b.patient_id,
    CASE WHEN b.diagnosis ILIKE '%Mental Health Concern%' THEN 'MH'
      WHEN b.diagnosis ILIKE '%Genito Urinary Infection%' OR b.diagnosis ILIKE '%GUI%' OR b.diagnosis ILIKE '%Post-Exposure%' THEN 'STI'
      WHEN b.diagnosis ILIKE '%Premature Ejaculation%' AND b.diagnosis ILIKE '%Erectile Dysfunction%' THEN 'ED+PE+'
      WHEN b.diagnosis ILIKE '%Erectile Dysfunction%' THEN 'ED+'
      WHEN b.diagnosis ILIKE '%Premature Ejaculation%' THEN 'PE+'
      WHEN b.diagnosis ILIKE '%Low Sexual Desire%' THEN 'LSD'
      WHEN b.diagnosis ILIKE '%Delayed Ejaculation%' THEN 'DE'
      WHEN b.diagnosis ILIKE '%Dyspareunia%' OR b.diagnosis ILIKE '%Pain during sex%' THEN 'DYS'
      WHEN b.diagnosis ILIKE '%Porn Addiction%' THEN 'PA'
      WHEN b.diagnosis ILIKE '%Compulsive Masturbation%' THEN 'CM'
      WHEN b.diagnosis ILIKE '%Vaginismus%' THEN 'VGS'
      WHEN b.diagnosis ILIKE '%Female Sexual Arousal Disorder%' THEN 'FSAD'
      WHEN b.diagnosis ILIKE '%Anorgasmia%' THEN 'AORG'
      WHEN b.diagnosis ILIKE '%Not Otherwise Specified%' THEN 'NOS' ELSE 'oth' END AS diag_cat
  FROM (SELECT enc.patient_id, LISTAGG(pqa.value, ',') AS diagnosis,
          RANK() OVER (PARTITION BY enc.patient_id ORDER BY enc.created_at DESC) AS rnk
        FROM allo_encounters.encounters enc
        LEFT JOIN allo_health.paperform_qa pqa ON pqa.encounter_id=enc.id AND pqa.deleted_at IS NULL AND pqa.title ILIKE '%diagnosis%'
        WHERE enc.deleted_at IS NULL AND LOWER(enc.type) LIKE '%merged-rx%'
        GROUP BY enc.patient_id, enc.created_at) b WHERE rnk=1
),
sc_online AS (
  SELECT apt.patient_id,
    date_trunc('week', apt.start_time + interval '5.5 hours')::date AS week_start,
    apt.status, COALESCE(pro.name,'—') AS doctor,
    COALESCE(dl.city,'Online') AS city, COALESCE(dl.locality,'Online') AS locality,
    COALESCE(pf.diag_cat,'oth') AS diagnosis,
    row_number() over (partition by apt.patient_id order by apt.created_at asc) AS attempt_rnk
  FROM allo_consultations.appointments apt
  JOIN allo_consultations.types t ON apt.type_id=t.id AND t.deleted_at IS NULL AND t.name='Screening Call'
  LEFT JOIN allo_persons.providers pro ON apt.provider_id=pro.id AND pro.deleted_at IS NULL
  LEFT JOIN doctor_location dl ON apt.provider_id=dl.provider_id AND DATE(apt.start_time+INTERVAL '5.5 hours')=dl.block_dt AND apt.block_id=dl.block_id
  LEFT JOIN paperform_qa pf ON pf.patient_id=apt.patient_id
  WHERE apt.deleted_at IS NULL
    AND apt.location_id IN ({TELE})   -- ONLINE = the 2 telehealth location UUIDs (sheet definition); city/locality from the doctor's block that day (dl), else 'Online'
),
lead_first AS (
  SELECT patient_id, date_trunc('week', lead_crt)::date AS lead_week,
    CASE
      WHEN lower(temp) IN ('directwalkin','googlelisting','googleslisting','gmb') THEN 'GMB'
      WHEN lower(temp)='google' THEN 'Google'
      WHEN lower(temp)='practo' THEN 'Practo'
      WHEN lower(temp) IN ('fb','facebook','meta','ig','instagram') THEN 'Meta'
      WHEN lower(temp) LIKE '%organic%' THEN 'Organic'
      WHEN temp IS NULL OR temp='' THEN 'Direct / none'
      ELSE 'Others' END AS source_bucket
  FROM (
    SELECT patient_id, lead_crt,
      CASE WHEN us2 IS NULL OR us2='' THEN us WHEN us2 IN ('fb','google') THEN us2 WHEN us2 IN ('googleslisting') THEN 'GMB' ELSE us END AS temp
    FROM (
      SELECT pat.id AS patient_id, date(ld.created_at + interval '5.5 hours') AS lead_crt,
        ld.utm_source AS us,
        regexp_replace(regexp_substr(ld.source_url,'utm_source=[^& ]+'),'utm_source=','') AS us2,
        row_number() over (partition by pat.id order by ld.created_at asc) AS lr
      FROM allo_persons.patient pat
      JOIN allo_persons.lead ld ON pat.phone_no=ld.phone_no AND ld.deleted_at IS NULL
      WHERE pat.deleted_at IS NULL) WHERE lr=1)
),
patient_comp AS (
  SELECT patient_id, MIN(week_start) AS first_comp_wk
  FROM sc_online WHERE status IN ('COMPLETED','RECONSULTED') GROUP BY patient_id
),
base AS (
  SELECT b.patient_id, b.doctor, b.city, b.locality, b.week_start, b.attempt_rnk, b.diagnosis,
    lf.lead_week, COALESCE(lf.source_bucket,'Direct / none') AS source_bucket, pc.first_comp_wk,
    CASE WHEN b.status IN ('COMPLETED','RECONSULTED') THEN 1 ELSE 0 END AS done_flag
  FROM sc_online b
  LEFT JOIN lead_first lf ON lf.patient_id=b.patient_id
  LEFT JOIN patient_comp pc ON pc.patient_id=b.patient_id
  WHERE b.week_start >= '{START_WK}'
),
bpw AS (
  SELECT patient_id, doctor, city, locality, source_bucket, week_start, attempt_rnk, diagnosis, lead_week, first_comp_wk, done_any FROM (
    SELECT base.*,
      MAX(done_flag) OVER (PARTITION BY patient_id, week_start, city, locality) AS done_any,
      row_number() OVER (PARTITION BY patient_id, week_start, city, locality ORDER BY attempt_rnk ASC) AS wk_rnk
    FROM base
  ) WHERE wk_rnk=1   -- one row per (patient, clinic-of-doctor's-block, week): counts a patient at EVERY city they had an online SC that week (matches the sheet + the offline cube; the old (patient,week) dedup lost Ranchi when the week-earliest attempt resolved to 'Online')
)
SELECT city, locality, doctor, source_bucket, week_start, diagnosis,
  -- booked = 1st-in-window SC (ft) + genuine returns (ret_return); EXCLUDES within-window rebooks (ret_rebook), which double-counted a patient who rebooked after a no-show → ties to the sheet (was count(distinct patient_id), inflated ~768 vs 571; B2D read 60% not 80%)
  count(distinct case when attempt_rnk=1 or (attempt_rnk>1 and first_comp_wk is not null and first_comp_wk<week_start) then patient_id end) AS booked,
  count(distinct case when done_any=1 then patient_id end) AS done,
  count(distinct case when attempt_rnk=1 and lead_week=week_start then patient_id end) AS ft_same,
  count(distinct case when attempt_rnk=1 and lead_week<week_start then patient_id end) AS ft_prev,
  count(distinct case when attempt_rnk=1 and (lead_week is null or lead_week>week_start) then patient_id end) AS ft_nolead,
  count(distinct case when attempt_rnk>1 then patient_id end) AS repeat_,
  count(distinct case when attempt_rnk>1 and first_comp_wk is not null and first_comp_wk<week_start then patient_id end) AS ret_return,
  count(distinct case when attempt_rnk>1 and (first_comp_wk is null or first_comp_wk>=week_start) then patient_id end) AS ret_rebook
FROM bpw GROUP BY 1,2,3,4,5,6 ORDER BY 1,2,3,4,5,6;
"""


def run(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("query failed:\n" + (p.stderr or "")[:800] + "\n"); sys.exit(1)
    return [ln.split("\t") for ln in p.stdout.strip().splitlines() if ln.strip()]


def main():
    rows = run(SQL)
    weeks = sorted({r[4] for r in rows})
    widx = {w: i for i, w in enumerate(weeks)}
    NW = len(weeks)
    FIELDS = ["booked", "done", "ft_same", "ft_prev", "ft_nolead", "repeat", "ret_return", "ret_rebook"]
    blank = lambda: {f: [0]*NW for f in FIELDS}
    clinics = {}
    for r in rows:
        city, loc, doctor, source, wk, cat = r[0], r[1], r[2], r[3], r[4], r[5]
        key = city + "|" + loc
        i = widx[wk]
        vals = [int(v) for v in r[6:14]]
        o = clinics.setdefault(key, blank())
        dd = o.setdefault("by_doctor", {}).setdefault(doctor, blank())
        ss = o.setdefault("by_source", {}).setdefault(source, blank())
        cc = o.setdefault("by_cat", {}).setdefault(cat, blank())   # done split by merged-Rx diagnosis category (for the ⑤ Done drill)
        csrc = o.setdefault("by_cat_source", {}).setdefault(cat, {})   # EXACT done × category × SOURCE (patient has one cat + one source) → no proportional estimate for online in ⑤
        if source not in csrc: csrc[source] = [0]*NW
        csrc[source][i] += vals[1]   # done
        for f, v in zip(FIELDS, vals):
            o[f][i] += v; dd[f][i] += v; ss[f][i] += v; cc[f][i] += v

    out = {"_meta": {"weeks": weeks,
                     "source": "allo_consultations.appointments · SC ONLINE (telehealth loc) attributed to the doctor's block clinic that day · Lead-to-Book additive · service week",
                     "note": "Per-clinic online (city|locality via doctor_location block join); unresolved → 'Online|Online'. Depth via by_doctor / by_source.",
                     "fields": FIELDS},
           "clinics": clinics}
    json.dump(out, open(os.path.join(ROOT, "data_sc_bookings_online.json"), "w"), separators=(",", ":"))
    natB = sum(clinics.get("Online|Online", blank())["booked"])
    tot = sum(sum(o["booked"]) for o in clinics.values())
    print(f"data_sc_bookings_online.json · {len(clinics)} clinic-keys · {NW} weeks ({weeks[0]}→{weeks[-1]})")
    print(f"  total online SC booked (all wks) {tot} · unresolved 'Online|Online' {natB} ({100*natB//max(1,tot)}%)")


if __name__ == "__main__":
    main()
