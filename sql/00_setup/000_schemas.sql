-- object : схемы stg, core, mart
-- grain  : -
-- source : -
-- cc     : -
-- why    : сборка с нуля и идемпотентна — каждый запуск пересоздаёт всё, кроме raw

DROP SCHEMA IF EXISTS stg CASCADE;
DROP SCHEMA IF EXISTS core CASCADE;
DROP SCHEMA IF EXISTS mart CASCADE;

CREATE SCHEMA stg;
CREATE SCHEMA core;
CREATE SCHEMA mart;

COMMENT ON SCHEMA stg IS 'Типизация и чистка raw: views, 1:1 с таблицами raw';
COMMENT ON SCHEMA core IS 'Модель: измерения и факты';
COMMENT ON SCHEMA mart IS 'Витрины для аналитики, ответов и графиков; DQ';
