-- object : mart.q01..q05 — ответы на вопросы аналитиков (docs/tasks.md, блок А)
-- grain  : по каждому вопросу — своя (месяц / продавец / одна строка / категория)
-- source : только mart.* и core.* — не raw
-- cc     : контрольные цифры проверяются в sql/80_dq/810_dq_checks.sql
-- why    : вопрос = view поверх витрины; новый вопрос добавляется одним view

-- Q1. Выручка и число заказов по месяцам, 2016-09..2018-08 (24 строки, 2016-11 = 0)
CREATE VIEW mart.q01_revenue_by_month AS
SELECT month, orders, revenue
FROM mart.v_sales_month
WHERE month BETWEEN DATE '2016-09-01' AND DATE '2018-08-01'
ORDER BY month;

-- Q2. Топ-10 продавцов по выручке — только их позиции
CREATE VIEW mart.q02_top_sellers AS
SELECT seller_id, city, state, orders, units, revenue
FROM mart.v_seller_sales
ORDER BY revenue DESC, seller_id
LIMIT 10;

-- Q3. Средний чек — на уровне заказа (товар + доставка), плюс строки и единицы на заказ
CREATE VIEW mart.q03_avg_check AS
SELECT
    ROUND(SUM(order_value) / COUNT(*), 2)  AS avg_check,
    ROUND(AVG(line_count), 4)              AS avg_lines,
    ROUND(AVG(line_count), 4)              AS avg_units
FROM mart.order_summary
WHERE is_revenue;

-- Q4. Покупатели (customer_unique_id) и доля вернувшихся за второй покупкой
CREATE VIEW mart.q04_repeat_customers AS
WITH c AS (
    SELECT customer_unique_id, COUNT(*) AS orders
    FROM mart.order_summary
    GROUP BY customer_unique_id
)
SELECT
    COUNT(*)                                                        AS customers,
    COUNT(*) FILTER (WHERE orders >= 2)                             AS returned,
    ROUND(100.0 * COUNT(*) FILTER (WHERE orders >= 2) / COUNT(*), 2) AS returned_pct
FROM c;

-- Q5. Выручка по категориям с долей; unknown — отдельная категория, сумма = общей выручке
CREATE VIEW mart.q05_revenue_by_category AS
SELECT label AS category, revenue, share_pct
FROM mart.v_category_sales
ORDER BY revenue DESC;
