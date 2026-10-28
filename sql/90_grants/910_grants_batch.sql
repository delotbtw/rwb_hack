-- object : гранты ingestor на ops.stream_pause
-- grain  : -
-- source : -
-- cc     : K3 §3.3, K0 §4.4
-- why    : протокол паузы: ingestor делает SELECT ... FOR SHARE, а FOR SHARE требует права UPDATE;
--          гранты в конце бандла, чтобы пережить пересоздание схем (900_grants.sql не меняется)

GRANT SELECT, UPDATE ON ops.stream_pause TO ingestor;
