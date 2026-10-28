-- object : mart.build_params, mart.etl_runs, mart.stream_status, mart.reconcile_result
-- grain  : как у одноимённых таблиц ops.*
-- source : ops.build_params, ops.etl_runs, ops.stream_status, ops.reconcile_result
-- cc     : K0 §3.2, §4.3
-- why    : API и Grafana читают только mart под app_ro; тонкие views дают доступ к служебным данным без прав на ops

CREATE VIEW mart.build_params AS SELECT * FROM ops.build_params;
CREATE VIEW mart.etl_runs AS SELECT * FROM ops.etl_runs;
CREATE VIEW mart.stream_status AS SELECT * FROM ops.stream_status;
CREATE VIEW mart.reconcile_result AS SELECT * FROM ops.reconcile_result;
