-- object : гранты ingestor на ops.replay_runs
-- grain  : -
-- source : -
-- cc     : K2 §6 п.3, ASSUMPTION-K2-1 (пробел K0)
-- why    : ingestor пишет итоги реплея и отмечает догон; 900_grants.sql не меняем, гранты потока — здесь

GRANT SELECT, INSERT, UPDATE ON ops.replay_runs TO ingestor;
