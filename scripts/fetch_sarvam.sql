-- Clinic Scorecard Phase-2 — Sarvam inbound-call quality (NETWORK / by-city snapshot).
-- call_analyses.created_at is the analysis-batch date (only ~last 2 weeks populated), and the
-- call->appointment link is sparse, so this is a recent network snapshot, NOT a per-clinic-week trend.
-- did_we_do_it = whether the agent accomplished the booking goal on the call.
SELECT
  json_extract_path_text(json_serialize(analysis),'user_intent','user_city','best_match')  AS city,
  json_extract_path_text(json_serialize(analysis),'user_intent','user_city','is_our_city') AS is_our_city,
  json_extract_path_text(json_serialize(analysis),'did_we_do_it','result')           AS ddwi,
  json_extract_path_text(json_serialize(analysis),'patient_intent_strength','result') AS intent,
  json_extract_path_text(json_serialize(analysis),'patient_dropped_mid_conversation','result') AS dropped,
  COUNT(*) AS n
FROM allo_analytics.call_analyses
WHERE deleted_at IS NULL AND created_at >= '2026-06-08'
  AND analysis IS NOT NULL AND json_serialize(analysis) <> 'null'
GROUP BY 1,2,3,4,5;
