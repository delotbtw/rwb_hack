-- object : core.fact_order_review
-- grain  : 1 строка = 1 связь отзыва с заказом; PK (review_id, order_id)
-- source : stg.order_reviews
-- cc     : 547 заказов с несколькими отзывами — все записи сохраняются, оценка заказа = среднее
-- why    : отсутствие отзыва не равно нулевой оценке — заказ без отзыва просто не попадает сюда

CREATE TABLE core.fact_order_review AS
SELECT
    review_id, order_id, review_score,
    review_comment_title, review_comment_message,
    review_comment_message IS NOT NULL AS has_text,
    review_created_at, review_answered_at
FROM stg.order_reviews;

ALTER TABLE core.fact_order_review ADD PRIMARY KEY (review_id, order_id);
ALTER TABLE core.fact_order_review
    ADD FOREIGN KEY (order_id) REFERENCES core.fact_order (order_id);
ALTER TABLE core.fact_order_review
    ADD CHECK (review_score BETWEEN 1 AND 5);
