-- Поддерживает выбор последнего отзыва на заказ без сортировки всей таблицы.
CREATE INDEX fact_order_review_latest_idx ON core.fact_order_review
    (order_id, review_answered_at DESC NULLS LAST,
     review_created_at DESC NULLS LAST, review_id DESC)
    INCLUDE (review_score);
