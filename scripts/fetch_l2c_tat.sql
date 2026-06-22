-- Time-to-first-OUTBOUND-call (TAT) for leads, last 4 weeks: how fast leads get dialled.
WITH ld AS (SELECT DISTINCT RIGHT(phone_no,10) AS ph, created_at AS ld_ts FROM allo_persons.lead
  WHERE phone_no IS NOT NULL AND LEN(phone_no)>=10 AND created_at>='2026-05-11' AND created_at< '2026-06-22'),
oc AS (SELECT RIGHT("to",10) AS ph, start_time AS ct FROM allo_vendors.exotel_calls
  WHERE direction IN ('outbound','outbound-api') AND deleted_at IS NULL AND start_time>='2026-05-11'),
first_call AS (SELECT ld.ph, MIN(oc.ct) AS first_ct, ld.ld_ts FROM ld JOIN oc ON oc.ph=ld.ph AND oc.ct>=ld.ld_ts AND oc.ct<=DATEADD(day,14,ld.ld_ts) GROUP BY ld.ph, ld.ld_ts)
SELECT CASE WHEN DATEDIFF(hour,ld_ts,first_ct)<=4 THEN '1_<=4h'
            WHEN DATEDIFF(hour,ld_ts,first_ct)<=24 THEN '2_same_day'
            WHEN DATEDIFF(hour,ld_ts,first_ct)<=72 THEN '3_1to3d'
            ELSE '4_3d+' END AS tat_bucket, COUNT(*) n
FROM first_call GROUP BY 1 ORDER BY 1;
