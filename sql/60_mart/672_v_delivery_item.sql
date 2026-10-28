-- object : mart.v_delivery_item
-- grain  : 1 строка = 1 позиция delivered-заказа (order_id, order_item_id)
-- source : core.fact_order_item, core.fact_order, core.dim_seller, mart.order_summary
-- cc     : is_shipped_late = передача перевозчику позже shipping_limit; NULL, если одной из дат нет; даты как в core
-- why    : срез по продавцу для D2 на грануле позиции без JOIN фактов в панелях; оценка и штат покупателя берутся из order_summary

CREATE VIEW mart.v_delivery_item AS
SELECT
    i.order_id,
    i.order_item_id,
    os.purchase_month,
    i.seller_id,
    s.state_normalized                                          AS seller_state,
    os.customer_state,
    o.delivered_carrier_at > i.shipping_limit_at                AS is_shipped_late,
    EXTRACT(EPOCH FROM o.delivered_carrier_at - i.shipping_limit_at) / 86400 AS ship_delay_days,
    os.review_score_mean
FROM core.fact_order_item i
LEFT JOIN core.fact_order o     ON o.order_id = i.order_id
LEFT JOIN core.dim_seller s     ON s.seller_id = i.seller_id
LEFT JOIN mart.order_summary os ON os.order_id = i.order_id
WHERE o.order_status = 'delivered';

COMMENT ON VIEW mart.v_delivery_item IS 'Позиция delivered-заказа: опоздание передачи перевозчику относительно shipping_limit, срезы продавец/штат';
