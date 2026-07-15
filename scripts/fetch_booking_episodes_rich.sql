-- WEEKLY booking cube: one booking per patient per WEEK (reschedules within the same Monday-week collapse;
-- a rebooking in a LATER week is a separate booking). So Mon+Thu (same wk) = one 1st-ever; next-Tue = a Retry.
--   ptype    : new (patient's first-ever week) | relapse (a later week, completed an SC in an earlier week)
--                                              | reattempt = "Retry" (a later week, never completed before)
--   lead_age : days from the week's lead → that week's first SC  → fresh/wk1/wk2_4/mo1_3/mo3
--   channel  : utm_source bucket ;  medium : call/web/whatsapp/book/walkin (from lead origin/user_flow)
WITH sc AS (
  SELECT a.patient_id, a.created_at, a.start_time, LOWER(a.status) AS st,
         CASE WHEN LOWER(a.status) IN ('completed','reconsulted') THEN 1 ELSE 0 END AS done_flag,
         TO_CHAR(DATE_TRUNC('week', a.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD') AS wk,
         loc.city, loc.locality, p.lead_id
  FROM allo_consultations.appointments a
  JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
  JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
  LEFT JOIN allo_persons.patient p ON p.id=a.patient_id
  WHERE a.deleted_at IS NULL
),
fow AS (   -- one row per patient-week = that week's FIRST SC (for attribution); week_done = completed that week?
  SELECT *, ROW_NUMBER() OVER (PARTITION BY patient_id, wk ORDER BY created_at) AS rn,
         MAX(done_flag) OVER (PARTITION BY patient_id, wk) AS week_done
  FROM sc
),
pw AS (SELECT * FROM fow WHERE rn=1),
seq AS (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY patient_id ORDER BY wk) AS wk_seq,
    SUM(week_done) OVER (PARTITION BY patient_id ORDER BY wk ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_done
  FROM pw
),
callcat AS (   -- each caller phone → their most-recent inbound call's AI-audit diagnosis category
  SELECT ph, cat FROM (
    SELECT RIGHT(ec."from",10) AS ph, COALESCE(ca.analysis.diagnoses.category::varchar,'NOT_MENTIONED') AS cat,
           ROW_NUMBER() OVER (PARTITION BY RIGHT(ec."from",10) ORDER BY ec.start_time DESC) AS rn
    FROM allo_analytics.call_analyses ca
    JOIN allo_vendors.exotel_calls ec ON ec.call_id=ca.call_id AND ec.routed_to='lead_to_call' AND ec.direction='inbound'
    WHERE ec.start_time >= '2025-11-01'
  ) q WHERE rn=1
),
joined AS (
  SELECT s.city, s.locality AS clinic, s.wk, s.week_done,
    CASE WHEN s.wk_seq=1 THEN 'new' WHEN s.prior_done>0 THEN 'relapse' ELSE 'reattempt' END AS ptype,
    CASE   -- lead maturity by CALENDAR WEEK (lead's week vs this booking's week) — 'fresh' = lead arrived the SAME week the SC is booked, so it ties exactly to ① "leads this week → booked this week"
      WHEN l.id IS NULL OR l.created_at IS NULL THEN 'nolead'
      WHEN DATE_TRUNC('week', l.created_at + INTERVAL '5.5 hours') > DATE_TRUNC('week', s.start_time + INTERVAL '5.5 hours') THEN 'nolead'   -- lead created after the booking week → didn't drive it
      WHEN DATEDIFF(week, DATE_TRUNC('week', l.created_at + INTERVAL '5.5 hours'), DATE_TRUNC('week', s.start_time + INTERVAL '5.5 hours')) = 0 THEN 'fresh'
      WHEN DATEDIFF(week, DATE_TRUNC('week', l.created_at + INTERVAL '5.5 hours'), DATE_TRUNC('week', s.start_time + INTERVAL '5.5 hours')) = 1 THEN 'wk1'
      WHEN DATEDIFF(week, DATE_TRUNC('week', l.created_at + INTERVAL '5.5 hours'), DATE_TRUNC('week', s.start_time + INTERVAL '5.5 hours')) BETWEEN 2 AND 4 THEN 'wk2_4'
      WHEN DATEDIFF(week, DATE_TRUNC('week', l.created_at + INTERVAL '5.5 hours'), DATE_TRUNC('week', s.start_time + INTERVAL '5.5 hours')) BETWEEN 5 AND 13 THEN 'mo1_3'
      ELSE 'mo3' END AS lead_age,   -- fresh=same wk · wk1=1 wk prior · wk2_4=2–4 · mo1_3=5–13 · mo3=14+ weeks earlier
    CASE
      WHEN l.gclid IS NOT NULL AND l.gclid<>'' THEN 'Google Ads'
      WHEN LOWER(COALESCE(l.utm_source,''))='google' AND LOWER(COALESCE(l.utm_medium,'')) LIKE '%cpc%' THEN 'Google Ads'
      WHEN LOWER(COALESCE(l.utm_source,''))='google' AND LOWER(COALESCE(l.utm_campaign,''))='inbound_call' THEN 'Google Ads'  -- google-source inbound calls (no gclid, medium=number not cpc); GMB calls are utm_source='gmb' so unaffected
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('gmb','googlelisting','google listing','google_listing') THEN 'Google Maps (GMB)'
      WHEN LOWER(COALESCE(l.utm_source,''))='practo' THEN 'Practo'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('fb','facebook','meta','ig','instagram') THEN 'Meta'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('justdial','jd') THEN 'JustDial'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('alloreferral','allorefferal','doctorreferral','referral') THEN 'Referral'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('chatgpt.com','youtube','moj') THEN 'AI / Social'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('organic','google','blog') AND LOWER(COALESCE(l.source_url,'')) LIKE '%/blog/%' THEN 'Organic · Blog'  -- blog content = organic sub-source (matches ① leads)
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('organic','google','blog') THEN 'Organic'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('directwalkin','walkin','walk-in') THEN 'Walk-in'
      WHEN LOWER(COALESCE(l.utm_source,''))='others' THEN 'Other (untracked)'
      WHEN l.id IS NULL OR COALESCE(l.utm_source,'')='' THEN 'No tag'
      ELSE 'Other' END AS channel,
    CASE
      WHEN l.id IS NULL THEN 'walkin'
      WHEN LOWER(COALESCE(l.utm_campaign,''))='inbound_call' THEN 'call'         -- inbound call; utm_medium = the number
      WHEN LOWER(COALESCE(l.utm_medium,''))='whatsapp' AND LOWER(COALESCE(l.utm_campaign,''))='outbound' THEN 'wa_outbound'  -- WhatsApp outbound-template flow (matches ① leads); before the generic 'outbound' below
      WHEN LOWER(COALESCE(l.utm_campaign,''))='outbound' THEN 'outbound'         -- L2C team CALLED the patient (not inbound demand)
      WHEN RIGHT(LOWER(COALESCE(l.utm_campaign,'')),3)='_wa' OR LOWER(COALESCE(l.origin,'')) LIKE '%whatsapp%' THEN 'whatsapp'   -- gmb_wa / organic_wa / …
      WHEN LOWER(COALESCE(l.utm_source,''))='practo' THEN 'book'
      WHEN LOWER(COALESCE(l.utm_campaign,'')) IN ('website','blog') OR (l.source_url IS NOT NULL AND l.source_url<>'') THEN 'web'
      WHEN LOWER(COALESCE(l.utm_source,'')) IN ('directwalkin','walkin','walk-in') THEN 'walkin'
      ELSE 'other' END AS medium,
    CASE WHEN LOWER(COALESCE(l.utm_campaign,''))='inbound_call' THEN RIGHT(REGEXP_REPLACE(COALESCE(l.utm_medium,''),'[^0-9]',''),10) ELSE '' END AS number,
    CASE WHEN (l.gclid IS NOT NULL AND l.gclid<>'')
           OR (LOWER(COALESCE(l.utm_source,''))='google' AND LOWER(COALESCE(l.utm_medium,'')) LIKE '%cpc%')
           OR LOWER(COALESCE(l.utm_source,'')) IN ('fb','facebook','meta','ig','instagram')
         THEN COALESCE(NULLIF(l.utm_campaign,''),'(none)') ELSE '' END AS campaign,   -- ad campaign for paid channels
    CASE WHEN LOWER(COALESCE(l.utm_campaign,''))='inbound_call'
      THEN CASE cc.cat WHEN 'SEXUAL_HEALTH_GENERAL' THEN 'SH' WHEN 'MENTAL_HEALTH' THEN 'MH'
                       WHEN 'STI' THEN 'STI' WHEN 'OTHER' THEN 'Other' WHEN 'NOT_MENTIONED' THEN 'Other'
                       ELSE 'unknown' END
      ELSE '' END AS category,   -- REAL per-call AI-audit category (call leads only)
    -- rank axes, computed AS-OF BEFORE this booking (all on unique patient-weeks):
    CASE WHEN s.wk_seq=1 THEN '1st' WHEN s.wk_seq=2 THEN '2nd' WHEN s.wk_seq=3 THEN '3rd' ELSE '4pl' END AS brank,   -- booking rank: 1st-ever / 2nd / 3rd / 4th+ booking week for this patient
    CASE WHEN COALESCE(s.prior_done,0)=0 THEN 'd0' WHEN s.prior_done=1 THEN 'd1' ELSE 'd2pl' END AS drank   -- done rank: had they COMPLETED an SC before this booking? never / once / 2+ times
  FROM seq s
  LEFT JOIN allo_persons.lead l ON s.lead_id=l.id
  LEFT JOIN callcat cc ON RIGHT(COALESCE(l.phone_no,''),10)=cc.ph
  WHERE s.start_time >= '2026-01-05' AND s.start_time < '2026-07-13'
    AND LOWER(COALESCE(s.locality,'')) <> 'online' AND s.locality IS NOT NULL
)
SELECT city, clinic, wk, ptype, lead_age, channel, medium, number, campaign, category, brank, drank, COUNT(*) AS bookings, SUM(week_done) AS done
FROM joined GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12 ORDER BY 1,2,3;
