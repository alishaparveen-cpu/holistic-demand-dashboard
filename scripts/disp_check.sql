-- Assess agent disposition quality for YESTERDAY (2026-07-09): fill-rate, reason vocab, and agreement with AI-audit locality.
WITH td AS (
  SELECT a.id AS task_id, a.user_id AS db_pat_id, c.id AS task_action_id, b.team
  FROM allo_tasks.tasks a
  LEFT JOIN allo_tasks.actions c ON c.task_id=a.id AND c.deleted_at IS NULL
  LEFT JOIN allo_tasks.types b ON b.id=a.type_id AND b.deleted_at IS NULL
  WHERE a.deleted_at IS NULL AND LOWER(b.team)='lead_to_call'
    AND DATE(a.created_at + INTERVAL '5.5 hours') = '2026-07-09'
),
ans AS (
  SELECT task_action_id,
    MAX(CASE WHEN title='Main Disposition' THEN answer END) AS main_dp,
    MAX(CASE WHEN title='Choose city' THEN answer END) AS city,
    MAX(CASE WHEN title='Choose clinic' THEN answer END) AS clinic,
    MAX(CASE WHEN title='Choose reason' THEN answer END) AS reason
  FROM allo_tasks.task_form_answers
  WHERE deleted_at IS NULL AND DATE(created_at + INTERVAL '5.5 hours') = '2026-07-09'
  GROUP BY task_action_id
)
-- (1) FILL RATE
SELECT '1_fill_rate' AS section, NULL AS k, COUNT(*) AS tasks,
  COUNT(a.main_dp) AS has_disp, COUNT(a.city) AS has_city, COUNT(a.clinic) AS has_clinic, COUNT(a.reason) AS has_reason
FROM td LEFT JOIN ans a ON a.task_action_id=td.task_action_id
UNION ALL
-- (2) top main dispositions
SELECT '2_main_dp', a.main_dp, COUNT(*), NULL,NULL,NULL,NULL
FROM td LEFT JOIN ans a ON a.task_action_id=td.task_action_id GROUP BY a.main_dp
UNION ALL
-- (3) top reasons (why not booked)
SELECT '3_reason', a.reason, COUNT(*), NULL,NULL,NULL,NULL
FROM td LEFT JOIN ans a ON a.task_action_id=td.task_action_id WHERE a.reason IS NOT NULL GROUP BY a.reason
ORDER BY 1, 3 DESC;
