-- object : проверки DQ (наполнение mart.dq_result)
-- grain  : 1 INSERT = 1 проверка
-- source : raw.*, core.*, mart.*
-- cc     : DQ-xx из ТЗ §9; контроль Q1 из tasks.md
-- why    : новая проверка = новый INSERT по этому же шаблону

INSERT INTO mart.dq_result (check_id, description, expected, actual, passed)
SELECT 'DQ-01', 'fact_order: строк столько же, сколько в raw.orders',
       (SELECT COUNT(*) FROM raw.orders)::text, COUNT(*)::text,
       COUNT(*) = (SELECT COUNT(*) FROM raw.orders)
FROM core.fact_order;

INSERT INTO mart.dq_result (check_id, description, expected, actual, passed)
SELECT 'DQ-02', 'fact_order_item: строк столько же, сколько в raw.order_items',
       (SELECT COUNT(*) FROM raw.order_items)::text, COUNT(*)::text,
       COUNT(*) = (SELECT COUNT(*) FROM raw.order_items)
FROM core.fact_order_item;

INSERT INTO mart.dq_result (check_id, description, expected, actual, passed)
SELECT 'DQ-03', 'fact_order: нет статусов unknown',
       '0', COUNT(*)::text, COUNT(*) = 0
FROM core.fact_order
WHERE order_status = 'unknown';

INSERT INTO mart.dq_result (check_id, description, expected, actual, passed)
SELECT 'Q1-CTRL', 'Q1: 24 месяца 2016-09..2018-08, итого выручка 13 221 498.11',
       '24 / 13221498.11', COUNT(*) || ' / ' || SUM(revenue),
       COUNT(*) = 24 AND SUM(revenue) = 13221498.11
FROM mart.v_sales_month
WHERE month BETWEEN DATE '2016-09-01' AND DATE '2018-08-01';
