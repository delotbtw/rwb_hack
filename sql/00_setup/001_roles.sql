-- object : роли app_ro (чтение mart для API/Grafana) и ingestor (запись в landing/core из потока)
-- grain  : -
-- source : -
-- cc     : NFR (разграничение доступа), K0 §4.4
-- why    : роли живут на уровне кластера и не пересоздаются; гранты выдаёт 900_grants.sql (схемы дропаются при сборке)
-- ASSUMPTION-K0-1: демо-пароль = имя роли (только локально); пользователь hack не меняется

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_ro') THEN
        CREATE ROLE app_ro LOGIN PASSWORD 'app_ro';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ingestor') THEN
        CREATE ROLE ingestor LOGIN PASSWORD 'ingestor';
    END IF;
END
$$;

ALTER ROLE app_ro SET statement_timeout = '5s';
ALTER ROLE app_ro SET default_transaction_read_only = on;
