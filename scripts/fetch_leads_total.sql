-- Network-wide TOTAL inbound leads per week (all sources in main_source_wise_leads), regardless of
-- whether the lead was routed to a clinic (call_location). Most leads have no call_location, so this
-- network total (~5.6k/wk) is far larger than the clinic-attributed offline subset (~1.1k/wk) — it is
-- the true top-of-funnel for the category demand funnel. Practo is an external feed and not included.
SELECT TO_CHAR(DATE(week)::date - 6,'YYYY-MM-DD') AS wk, COUNT(*) AS all_leads
FROM production.public.main_source_wise_leads
WHERE week >= '2026-03-09' AND week < '2026-06-02'
GROUP BY 1 ORDER BY 1
