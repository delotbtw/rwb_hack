-- object : mart.dq_result, mart.build_info
-- grain  : dq_result — 1 строка = 1 проверка; build_info — 1 строка на сборку
-- source : -
-- cc     : NFR (самопроверки)
-- why    : результаты проверок лежат в базе и видны любому клиенту

CREATE TABLE mart.dq_result (
    check_id    text PRIMARY KEY,
    description text NOT NULL,
    expected    text NOT NULL,
    actual      text,
    passed      boolean NOT NULL,
    checked_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE mart.build_info AS
SELECT now() AS built_at;
