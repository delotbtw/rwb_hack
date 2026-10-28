-- object : mart.v_review_delivery, mart.v_review_delivery_summary
-- grain  : заказ; оценка 1–5
-- source : core.fact_order_review, mart.order_summary
-- cc     : Q6–Q10; независимые факты не размножаются
-- why    : определения нового ноутбука без изменения Q1–Q5

CREATE VIEW mart.v_review_delivery AS
WITH latest AS (
    SELECT DISTINCT ON (order_id) order_id, review_score
    FROM core.fact_order_review
    ORDER BY order_id, review_answered_at DESC NULLS LAST,
             review_created_at DESC NULLS LAST, review_id DESC
)
SELECT o.*, r.review_score
FROM mart.order_summary o
LEFT JOIN latest r ON r.order_id = o.order_id
WHERE o.is_valid_delivery;

CREATE VIEW mart.v_review_delivery_summary AS
SELECT s.score, COUNT(r.order_id) AS orders, AVG(r.delivery_days) AS mean_delivery_days,
       100.0 * COUNT(r.order_id) FILTER (WHERE r.delay_days > 0)
         / NULLIF(COUNT(r.order_id), 0) AS late_pct
FROM generate_series(1, 5) AS s(score)
LEFT JOIN mart.v_review_delivery r ON r.review_score = s.score
GROUP BY s.score;
