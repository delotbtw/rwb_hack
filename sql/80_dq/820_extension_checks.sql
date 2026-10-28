-- object : mart.dq_result
-- grain  : проверка сохранения фактов Q6–Q10
-- source : core.fact_order_payment, mart.order_summary, mart.v_payment_context, mart.v_order_status_snapshot, mart.v_review_delivery_summary
-- cc     : Q6–Q10; проверки применимы и при cutoff, и до реплея
-- why    : расширение не теряет платежи, заказы и выбранные отзывы

INSERT INTO mart.dq_result (check_id, description, expected, actual, passed)
SELECT check_id, description, expected::text, actual::text, expected = actual
FROM (VALUES
    ('EXT-PAYMENTS', 'Платежи не размножаются',
     (SELECT COUNT(*) FROM core.fact_order_payment),
     (SELECT COUNT(*) FROM mart.v_payment_context)),
    ('EXT-STATUSES', 'Распределение статусов сохраняет все заказы',
     (SELECT COUNT(*) FROM mart.order_summary),
     (SELECT COALESCE(SUM(orders), 0)::bigint FROM mart.v_order_status_snapshot)),
    ('EXT-WITHOUT-ITEMS', 'Заказы без позиций сохранены',
     (SELECT COUNT(*) FROM mart.order_summary WHERE NOT has_items),
     (SELECT COALESCE(SUM(without_items), 0)::bigint FROM mart.v_order_status_snapshot)),
    ('EXT-REVIEW-SCORES', 'Все пять оценок представлены', 5::bigint,
     (SELECT COUNT(*) FROM mart.v_review_delivery_summary))
) AS checks(check_id, description, expected, actual);
