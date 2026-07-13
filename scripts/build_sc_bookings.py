#!/usr/bin/env python3
"""Build data_sc_bookings.json — SC-offline booking funnel, reconciled to the L2 "Lead to Book funnel".

METHODOLOGY = L2 Lead-to-Book (ADDITIVE):
  - Screening Call, offline = lower(loc.name) NOT LIKE '%online%'
  - attempt_rnk = row_number over the patient's SC-offline appts by created_at (first SC = first-time)
  - base_patient_week: each patient assigned to ONE (clinic) per service week = their earliest-attempt clinic
    → so clinic totals SUM to city SUM to national (no non-additivity, exact at every grain incl. ad-hoc)
  - service week = DATE_TRUNC('week', start_time + 5.5h)

Per clinic ("City|Locality") × week:
  booked   = distinct patient (assigned to this clinic that week)
  done     = distinct patient who COMPLETED an offline SC that week (status COMPLETED/RECONSULTED)
  ft_same  = 1st-time (attempt_rnk=1) whose first lead landed the SAME week   (fast demand)
  ft_prev  = 1st-time whose first lead landed an EARLIER week                 (backlog/lag)
  ft_nolead= 1st-time with no lead (or lead after booking)
  repeat   = booked − 1st-time  (attempt_rnk>1 — prior SC attempt)
  (1st-time total = ft_same + ft_prev + ft_nolead)

Additive → the master just sums clinics for any scope. Run: AWS_PROFILE=redshift-data python3 scripts/build_sc_bookings.py
"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
START_WK = "2025-07-01"

SQL = f"""
WITH sc_offline AS (
  SELECT apt.patient_id,
    date_trunc('week', apt.start_time + interval '5.5 hours')::date AS week_start,
    apt.status,
    CASE   -- slot outcome (city-head "RD - 1st Bookings" appt_final_status logic): where the booked slot ended up
      WHEN apt.status IN ('SCHEDULED','PATIENT_JOINED','IN_PROGRESS','PROVIDER_JOINED') THEN 'SCHEDULED'
      WHEN lower(apt.status)='cancelled' THEN 'CANCELLED'
      WHEN apt.status IN ('RECONSULTED','COMPLETED') THEN 'COMPLETED'
      WHEN apt.updated_at > apt.start_time THEN 'No Show'
      WHEN apt.updated_at <= apt.start_time THEN 'Reschedule'
      ELSE 'Others' END AS slot_status,
    loc.city, loc.locality AS clinic, COALESCE(pro.name,'—') AS doctor,
    EXTRACT(dow FROM apt.start_time + interval '5.5 hours') AS dow,   -- 0=Sun … 6=Sat, IST (appt day for velocity split)
    row_number() over (partition by apt.patient_id order by apt.created_at asc) AS attempt_rnk
  FROM allo_consultations.appointments apt
  JOIN allo_consultations.types t ON apt.type_id=t.id AND t.deleted_at IS NULL AND t.name='Screening Call'
  JOIN allo_health.locations loc ON apt.location_id=loc.id AND loc.deleted_at IS NULL AND lower(loc.name) NOT LIKE '%online%'
  LEFT JOIN allo_persons.providers pro ON apt.provider_id=pro.id AND pro.deleted_at IS NULL
  WHERE apt.deleted_at IS NULL
),
lead_first AS (   -- patient's first-ever lead: week + source bucket (L2 Lead-to-Book source logic, enriched)
  SELECT patient_id, date_trunc('week', lead_crt)::date AS lead_week,
    CASE
      WHEN lower(temp) IN ('googlelisting','googleslisting','gmb') THEN 'GMB'   -- directwalkin excluded (city-head GMB = listing only, matches sheet)
      WHEN lower(temp)='google' THEN 'Google'
      WHEN lower(temp)='practo' THEN 'Practo'
      WHEN lower(temp) IN ('fb','facebook','meta','ig','instagram') THEN 'Meta'
      WHEN lower(temp) LIKE '%organic%' THEN 'Organic'
      WHEN temp IS NULL OR temp='' THEN 'Direct / none'
      ELSE 'Others' END AS source_bucket   -- directwalkin + justdial/marketing/misc land here (sheet 'Others')
  FROM (
    SELECT patient_id, lead_crt,
      CASE WHEN lower(us)='directwalkin' THEN 'directwalkin'   -- walk-in stays a walk-in even if the lead URL carries a fb/google utm
        WHEN us2 IS NULL OR us2='' THEN us WHEN us2 IN ('fb','google') THEN us2 WHEN us2 IN ('googleslisting') THEN 'GMB' ELSE us END AS temp
    FROM (
      SELECT pat.id AS patient_id, date(ld.created_at + interval '5.5 hours') AS lead_crt,
        ld.utm_source AS us,
        regexp_replace(regexp_substr(ld.source_url,'utm_source=[^& ]+'),'utm_source=','') AS us2,
        row_number() over (partition by pat.id order by ld.created_at asc) AS lr
      FROM allo_persons.patient pat
      JOIN allo_persons.lead ld ON pat.phone_no=ld.phone_no AND ld.deleted_at IS NULL
      WHERE pat.deleted_at IS NULL) WHERE lr=1)
),
patient_comp AS (   -- earliest week the patient ever COMPLETED an offline SC (for rebook vs return)
  SELECT patient_id, MIN(week_start) AS first_comp_wk
  FROM sc_offline WHERE status IN ('COMPLETED','RECONSULTED') GROUP BY patient_id
),
base AS (
  SELECT b.patient_id, b.city, b.clinic, b.doctor, b.week_start, b.attempt_rnk, b.dow, b.slot_status,
    lf.lead_week, COALESCE(lf.source_bucket,'Direct / none') AS source_bucket, pc.first_comp_wk,
    CASE WHEN b.status IN ('COMPLETED','RECONSULTED') THEN 1 ELSE 0 END AS done_flag
  FROM sc_offline b
  LEFT JOIN lead_first lf ON lf.patient_id=b.patient_id
  LEFT JOIN patient_comp pc ON pc.patient_id=b.patient_id
  WHERE b.week_start >= '{START_WK}'
),
bpw AS (
  SELECT patient_id, city, clinic, doctor, source_bucket, week_start, attempt_rnk, dow, lead_week, first_comp_wk, done_any FROM (
    SELECT base.*,
      MAX(done_flag) OVER (PARTITION BY patient_id, week_start, city, clinic) AS done_any,
      row_number() OVER (PARTITION BY patient_id, week_start, city, clinic ORDER BY attempt_rnk ASC) AS wk_rnk
    FROM base
  ) WHERE wk_rnk=1   -- one row per (patient, clinic, week): counts a patient at EVERY clinic they booked (matches city-head per-clinic view; multi-clinic patients count once per clinic)
),
bpwf AS (   -- add grain-primary flags so national/city rollups can de-dup a patient who booked at >1 clinic that week
  SELECT bpw.*,
    row_number() OVER (PARTITION BY patient_id, week_start ORDER BY attempt_rnk ASC) AS nat_rnk,          -- =1 at the patient's globally-earliest clinic that week
    row_number() OVER (PARTITION BY patient_id, week_start, city ORDER BY attempt_rnk ASC) AS city_rnk,   -- =1 at the patient's earliest clinic within that city
    MAX(done_any) OVER (PARTITION BY patient_id, week_start) AS done_glob,       -- completed at ANY clinic that week
    MAX(done_any) OVER (PARTITION BY patient_id, week_start, city) AS done_cty   -- completed at any clinic in that city
  FROM bpw
),
slots AS (   -- SLOT level (appointment rows, NOT distinct patient): booked slots + done slots + outcome breakdown, per clinic×source×doctor×week
  SELECT city, clinic, doctor, COALESCE(source_bucket,'Direct / none') AS source_bucket, week_start,
    count(*) AS booked_slots, sum(done_flag) AS done_slots,
    sum(case when slot_status='COMPLETED'  then 1 else 0 end) AS st_completed,
    sum(case when slot_status='SCHEDULED'  then 1 else 0 end) AS st_scheduled,
    sum(case when slot_status='No Show'    then 1 else 0 end) AS st_noshow,
    sum(case when slot_status='Reschedule' then 1 else 0 end) AS st_reschedule,
    sum(case when slot_status='CANCELLED'  then 1 else 0 end) AS st_cancelled,
    sum(case when slot_status='Others'     then 1 else 0 end) AS st_others
  FROM base GROUP BY 1,2,3,4,5
)
SELECT p.*, COALESCE(s.booked_slots,0) AS booked_slots, COALESCE(s.done_slots,0) AS done_slots,
  COALESCE(s.st_completed,0) AS st_completed, COALESCE(s.st_scheduled,0) AS st_scheduled,
  COALESCE(s.st_noshow,0) AS st_noshow, COALESCE(s.st_reschedule,0) AS st_reschedule,
  COALESCE(s.st_cancelled,0) AS st_cancelled, COALESCE(s.st_others,0) AS st_others FROM (
SELECT city, clinic, doctor, source_bucket, week_start,
  count(distinct patient_id) AS booked,
  count(distinct case when nat_rnk=1 then patient_id end) AS booked_nat,          -- national-distinct (sum over clinics = patient-level national)
  count(distinct case when city_rnk=1 then patient_id end) AS booked_city,        -- city-distinct   (sum over a city's clinics = patient-level city)
  count(distinct case when done_any=1 then patient_id end) AS done,
  count(distinct case when nat_rnk=1 and done_glob=1 then patient_id end) AS done_nat,
  count(distinct case when city_rnk=1 and done_cty=1 then patient_id end) AS done_city,
  count(distinct case when attempt_rnk=1 and lead_week=week_start then patient_id end) AS ft_same,
  count(distinct case when attempt_rnk=1 and lead_week<week_start then patient_id end) AS ft_prev,
  count(distinct case when attempt_rnk=1 and (lead_week is null or lead_week>week_start) then patient_id end) AS ft_nolead,
  count(distinct case when attempt_rnk>1 then patient_id end) AS repeat_,
  count(distinct case when attempt_rnk>1 and first_comp_wk is not null and first_comp_wk<week_start then patient_id end) AS ret_return,
  count(distinct case when attempt_rnk>1 and (first_comp_wk is null or first_comp_wk>=week_start) then patient_id end) AS ret_rebook,
  count(distinct case when dow NOT IN (0,6) then patient_id end) AS bkwd,   -- weekday bookings (rep. appt day)
  count(distinct case when dow IN (0,6) then patient_id end) AS bkwe,       -- weekend bookings
  count(distinct case when done_any=1 and dow NOT IN (0,6) then patient_id end) AS done_wkday,   -- weekday DONE (for done-velocity)
  count(distinct case when done_any=1 and dow IN (0,6) then patient_id end) AS done_wkend,       -- weekend DONE
  count(distinct case when attempt_rnk=1 and DATEDIFF('week',lead_week,week_start)=1 then patient_id end) AS ft_prev_1w,          -- older-lead bookings, binned by lead age
  count(distinct case when attempt_rnk=1 and DATEDIFF('week',lead_week,week_start) between 2 and 4 then patient_id end) AS ft_prev_2_4w,
  count(distinct case when attempt_rnk=1 and DATEDIFF('week',lead_week,week_start) between 5 and 13 then patient_id end) AS ft_prev_1_3mo,
  count(distinct case when attempt_rnk=1 and DATEDIFF('week',lead_week,week_start)>13 then patient_id end) AS ft_prev_3mo
FROM bpwf GROUP BY 1,2,3,4,5
) p LEFT JOIN slots s ON s.city=p.city AND s.clinic=p.clinic AND s.doctor=p.doctor AND s.source_bucket=p.source_bucket AND s.week_start=p.week_start
ORDER BY 1,2,3,4,5;
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
    FIELDS = ["booked", "booked_nat", "booked_city", "done", "done_nat", "done_city",
              "ft_same", "ft_prev", "ft_nolead", "repeat", "ret_return", "ret_rebook", "bkwd", "bkwe", "done_wkday", "done_wkend",
              "ft_prev_1w", "ft_prev_2_4w", "ft_prev_1_3mo", "ft_prev_3mo",
              "booked_slots", "done_slots",   # SLOT level = appointment rows (patient-level = distinct-patient counts above)
              "st_completed", "st_scheduled", "st_noshow", "st_reschedule", "st_cancelled", "st_others"]   # slot outcome breakdown (sums to booked_slots)

    def blank():
        return {f: [0]*NW for f in FIELDS}

    clinics = {}
    for r in rows:
        city, clinic, doctor, source, wk = r[0], r[1], r[2], r[3], r[4]
        key = f"{city}|{clinic}"
        i = widx[wk]
        vals = [int(v) for v in r[5:33]]
        o = clinics.setdefault(key, blank())
        dd = o.setdefault("by_doctor", {}).setdefault(doctor, blank())
        ss = o.setdefault("by_source", {}).setdefault(source, blank())
        for f, v in zip(FIELDS, vals):
            o[f][i] += v          # clinic total
            dd[f][i] += v          # per doctor (sum over source)
            ss[f][i] += v          # per source (sum over doctor)

    out = {"_meta": {"weeks": weeks,
                     "source": "allo_consultations.appointments · SC offline (loc.name) · Lead-to-Book additive · service week",
                     "note": "Additive: sum clinics for any scope. 1st-time = ft_same+ft_prev+ft_nolead; repeat = booked - 1st-time.",
                     "fields": FIELDS},
           "clinics": clinics}
    json.dump(out, open(os.path.join(ROOT, "data_sc_bookings.json"), "w"), separators=(",", ":"))

    # verify vs L2 (22-28 Jun)
    vwk = "2026-06-22"
    def csum(cityname, f):
        return sum(o[f][widx[vwk]] for k, o in clinics.items() if k.split("|")[0] == cityname) if vwk in widx else 0
    natl = {f: sum(o[f][widx[vwk]] for o in clinics.values()) for f in FIELDS} if vwk in widx else {}
    print(f"data_sc_bookings.json · {len(clinics)} clinics · {NW} weeks ({weeks[0]}→{weeks[-1]})")
    print(f"\n── verify {vwk} (L2 Lead-to-Book targets) ──")
    tgt = {"Bangalore": (387, 222, 81), "Mumbai": (220, 122, 39), "Pune": (211, 132, 41),
           "Hyderabad": (153, 106, 18), "Chennai": (148, 94, 26)}
    for c, (b, fs, fp) in tgt.items():
        print(f"  {c:11} booked/clinic-sum {csum(c,'booked'):4} · city-distinct {csum(c,'booked_city'):4} ({b})  ft_same {csum(c,'ft_same'):4} ({fs})  done/clinic {csum(c,'done'):4} · city {csum(c,'done_city'):4}")
    print(f"  NATIONAL   booked: clinic-sum {natl.get('booked')} (inflated) · nat-distinct {natl.get('booked_nat')} (~1640 sheet)  |  "
          f"done: clinic-sum {natl.get('done')} · nat-distinct {natl.get('done_nat')} (988 sheet)")


if __name__ == "__main__":
    main()
