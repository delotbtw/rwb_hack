-- object : схемы landing и ops
-- grain  : -
-- source : -
-- cc     : K0 §3.1
-- why    : 000_schemas.sql дропает stg/core/mart на каждой сборке; журнал событий и служебные таблицы
--          должны пережить сборку, поэтому схемы создаются IF NOT EXISTS и никогда не дропаются

CREATE SCHEMA IF NOT EXISTS landing;
CREATE SCHEMA IF NOT EXISTS ops;

COMMENT ON SCHEMA landing IS 'Журнал входящих событий real-time; не пересоздаётся при сборке';
COMMENT ON SCHEMA ops IS 'Служебные таблицы: запуски ETL, статус потока, сверка, параметры сборки; не пересоздаётся';
