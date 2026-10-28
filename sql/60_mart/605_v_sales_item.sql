-- object : mart.v_sales_item
-- grain  : 1 строка = 1 позиция заказа (order_id, order_item_id), все статусы заказа
-- source : core.fact_order_item, core.fact_order, core.dim_order_status, core.dim_seller, core.dim_product, core.dim_category, core.dim_customer
-- cc     : FR-30 выручка = SUM(price) по is_revenue, без freight; месяц по purchase; покупатель = customer_unique_id
-- why    : единая гранула позиции для выручки, единиц и срезов по продавцу/категории без JOIN фактов в панелях (К5)

CREATE VIEW mart.v_sales_item AS
SELECT
    i.order_id,
    i.order_item_id,
    o.purchased_at                                   AS purchase_ts,
    date_trunc('month', o.purchased_at)::date        AS purchase_month,
    o.order_status,
    COALESCE(st.is_revenue, FALSE)                   AS is_revenue,
    i.seller_id,
    s.state_normalized                               AS seller_state,
    c.category_key,
    c.label                                          AS category_label,
    cu.customer_unique_id,
    cu.state_normalized                              AS customer_state,
    i.price,
    i.freight_value
FROM core.fact_order_item i
LEFT JOIN core.fact_order o        ON o.order_id = i.order_id
LEFT JOIN core.dim_order_status st ON st.order_status = o.order_status
LEFT JOIN core.dim_seller s        ON s.seller_id = i.seller_id
LEFT JOIN core.dim_product p       ON p.product_id = i.product_id
LEFT JOIN core.dim_category c      ON c.category_key = COALESCE(p.category_key, '__unknown__')
LEFT JOIN core.dim_customer cu     ON cu.customer_id = o.customer_id;

COMMENT ON VIEW mart.v_sales_item IS 'Позиция заказа: выручка, фрахт и срезы месяц/статус/продавец/категория/покупатель';
