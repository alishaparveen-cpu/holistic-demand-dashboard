-- Qualified-lead funnel per clinic/week/source from the MAINTAINED weekly demand superset.
-- relevant = agent/Sarvam-AI "relevant" flag on inbound calls. week is week-ENDING (Sunday).
SELECT city, locality, TO_CHAR(week,'YYYY-MM-DD') AS wk_end, COALESCE(final_source,'(none)') AS final_source,
  SUM(lead_count) AS leads, SUM(lead_count_relevant) AS relevant, SUM(lead_count_booked) AS booked,
  SUM(same_week_lead_booked) AS sw_booked, SUM(prev_week_lead_booked) AS pw_booked,
  SUM(new_users_booked) AS new_booked, SUM(calls_done) AS calls_done,
  SUM(first_attempt_slots) AS a1, SUM(second_attempt_slots) AS a2,
  SUM(third_attempt_slots) AS a3, SUM(more_than_third_attempt_slots) AS a3plus
FROM production.public.demand_data_week_superset
WHERE week >= '2026-03-22' AND week <= '2026-06-14'
GROUP BY 1,2,3,4 ORDER BY 1,2,3
