-- object : stg.order_reviews
-- grain  : 1 строка = 1 связь отзыва с заказом; ключ (review_id, order_id)
-- source : raw.order_reviews
-- cc     : review_id не уникален сам по себе, у 547 заказов несколько отзывов — DISTINCT не делаем
-- why    : оценка в int, пустой текст отзыва — NULL, а не пустая строка

CREATE VIEW stg.order_reviews AS
SELECT
    NULLIF(TRIM(review_id), '')                           AS review_id,
    NULLIF(TRIM(order_id), '')                            AS order_id,
    NULLIF(TRIM(review_score), '')::int                   AS review_score,
    NULLIF(TRIM(review_comment_title), '')                AS review_comment_title,
    NULLIF(TRIM(review_comment_message), '')              AS review_comment_message,
    NULLIF(TRIM(review_creation_date), '')::timestamp     AS review_created_at,
    NULLIF(TRIM(review_answer_timestamp), '')::timestamp  AS review_answered_at
FROM raw.order_reviews;
