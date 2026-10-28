-- object : mart.replay_runs
-- grain  : как у ops.replay_runs
-- source : ops.replay_runs
-- cc     : K2 §6 п.3
-- why    : API (/api/status, «Контроль») читает только mart под app_ro; view даёт доступ к итогам реплея без прав на ops

CREATE VIEW mart.replay_runs AS SELECT * FROM ops.replay_runs;
