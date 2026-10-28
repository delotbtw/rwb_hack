-- object : гранты ролей app_ro и ingestor
-- grain  : -
-- source : -
-- cc     : NFR (разграничение доступа), K0 §3.3, §4.4
-- why    : схемы stg/core/mart пересоздаются на каждой сборке и теряют GRANT, поэтому гранты
--          выдаются в последнем файле бандла; GRANT идемпотентен

-- app_ro: только чтение mart (core, raw, landing, ops недоступны)
GRANT USAGE ON SCHEMA mart TO app_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA mart TO app_ro;

-- ingestor: запись событий в landing и применение их в core
GRANT USAGE, CREATE ON SCHEMA landing TO ingestor;
GRANT ALL ON ALL TABLES IN SCHEMA landing TO ingestor;
GRANT ALL ON ALL SEQUENCES IN SCHEMA landing TO ingestor;

GRANT USAGE ON SCHEMA core TO ingestor;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA core TO ingestor;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA core TO ingestor;

-- ingestor: статус потока и параметры сборки
-- SELECT на stream_status нужен для UPDATE ... WHERE id = 1
GRANT USAGE ON SCHEMA ops TO ingestor;
GRANT SELECT, UPDATE ON ops.stream_status TO ingestor;
GRANT SELECT ON ops.build_params TO ingestor;
