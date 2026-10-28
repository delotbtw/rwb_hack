-- object : mart.v_delivery_review
-- grain  : 1 строка = 1 группа опоздания (В срок / 1–3 / 4–7 / >7 дней)
-- source : mart.order_summary
-- cc     : только валидные delivered с отзывом; оценка заказа = среднее его отзывов, затем среднее по заказам
-- why    : связь опоздания и оценки — наблюдение, не причинный эффект

CREATE VIEW mart.v_delivery_review AS
WITH g AS (
    SELECT
        CASE
            WHEN delay_days <= 0 THEN 1
            WHEN delay_days <= 3 THEN 2
            WHEN delay_days <= 7 THEN 3
            ELSE 4
        END AS group_order,
        review_score_mean
    FROM mart.order_summary
    WHERE is_valid_delivery AND review_score_mean IS NOT NULL
)
SELECT
    group_order,
    (ARRAY['В срок', '1–3 дня', '4–7 дней', 'Более 7 дней'])[group_order] AS delay_group,
    COUNT(*)                                AS orders,
    AVG(review_score_mean)::numeric(4, 2)   AS mean_score
FROM g
GROUP BY group_order
ORDER BY group_order;
