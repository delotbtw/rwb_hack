-- object : mart.v_order_seq, mart.v_cohort_retention
-- grain  : v_order_seq = 1 заказ (order_id, все статусы); v_cohort_retention = когорта × месяц жизни × штат первого заказа × категория первого заказа
-- source : mart.order_summary, mart.v_sales_item, mart.v_order_seq
-- cc     : покупатель = customer_unique_id; когорта = месяц первого заказа; удержание неаддитивно: SUM(active_customers) / SUM(cohort_size), не AVG(retention_rate)
-- why    : номер заказа покупателя для «новые / повторные» и матрица удержания 0..24 месяца для D3; месяцы вне наблюдаемого периода не выводятся, чтобы не занижать долю

CREATE VIEW mart.v_order_seq AS
WITH order_category AS (
    SELECT DISTINCT ON (order_id) order_id, category_label
    FROM mart.v_sales_item
    ORDER BY order_id, order_item_id
)
SELECT
    os.order_id,
    os.customer_unique_id,
    os.customer_state,
    os.purchase_month,
    FIRST_VALUE(oc.category_label) OVER (
        PARTITION BY os.customer_unique_id ORDER BY os.purchased_at, os.order_id
    )                                                                                          AS first_category,
    ROW_NUMBER() OVER (PARTITION BY os.customer_unique_id ORDER BY os.purchased_at, os.order_id) AS customer_order_seq,
    ROW_NUMBER() OVER (PARTITION BY os.customer_unique_id ORDER BY os.purchased_at, os.order_id) = 1 AS is_first_order
FROM mart.order_summary os
LEFT JOIN order_category oc ON oc.order_id = os.order_id;

COMMENT ON VIEW mart.v_order_seq IS 'Заказ с порядковым номером у покупателя (customer_unique_id) и категорией его первого заказа';

CREATE VIEW mart.v_cohort_retention AS
WITH firsts AS (
    SELECT customer_unique_id,
           purchase_month  AS cohort_month,
           customer_state  AS first_state,
           first_category
    FROM mart.v_order_seq
    WHERE is_first_order
),
cohorts AS (
    SELECT cohort_month, first_state, first_category, COUNT(*) AS cohort_size
    FROM firsts
    GROUP BY cohort_month, first_state, first_category
),
activity AS (
    SELECT
        f.cohort_month,
        f.first_state,
        f.first_category,
        ((EXTRACT(YEAR FROM s.purchase_month) - EXTRACT(YEAR FROM f.cohort_month)) * 12
         + EXTRACT(MONTH FROM s.purchase_month) - EXTRACT(MONTH FROM f.cohort_month))::int AS month_offset,
        COUNT(DISTINCT s.customer_unique_id) AS active_customers
    FROM mart.v_order_seq s
    JOIN firsts f ON f.customer_unique_id = s.customer_unique_id
    GROUP BY 1, 2, 3, 4
),
bounds AS (
    SELECT MAX(purchase_month) AS last_month FROM mart.v_order_seq
)
SELECT
    c.cohort_month,
    g.month_offset,
    c.first_state,
    c.first_category,
    c.cohort_size,
    COALESCE(a.active_customers, 0)                                         AS active_customers,
    ROUND(COALESCE(a.active_customers, 0)::numeric / c.cohort_size, 4)      AS retention_rate
FROM cohorts c
CROSS JOIN bounds b
CROSS JOIN generate_series(0, 24) AS g(month_offset)
LEFT JOIN activity a
       ON a.cohort_month = c.cohort_month
      AND a.month_offset = g.month_offset
      AND a.first_state IS NOT DISTINCT FROM c.first_state
      AND a.first_category IS NOT DISTINCT FROM c.first_category
WHERE (c.cohort_month + make_interval(months => g.month_offset))::date <= b.last_month;

COMMENT ON VIEW mart.v_cohort_retention IS 'Удержание: когорта (месяц 1-го заказа) × месяц жизни 0..24 × штат × категория 1-го заказа; только наблюдаемые месяцы';
