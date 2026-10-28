-- object : core.fact_order
-- grain  : 1 строка = 1 заказ; PK order_id
-- source : stg.orders, core.dim_order_status
-- cc     : неизвестный статус → 'unknown' (unknown-member), строка не теряется
-- why    : заказ — отдельный факт, позиции не смешиваются с ним по грануле

CREATE TABLE core.fact_order AS
SELECT
    o.order_id,
    o.customer_id,
    COALESCE(s.order_status, 'unknown') AS order_status,
    o.purchased_at,
    o.approved_at,
    o.delivered_carrier_at,
    o.delivered_customer_at,
    o.estimated_delivery_at
FROM stg.orders o
LEFT JOIN core.dim_order_status s ON s.order_status = o.order_status;

ALTER TABLE core.fact_order ADD PRIMARY KEY (order_id);
ALTER TABLE core.fact_order
    ADD FOREIGN KEY (order_status) REFERENCES core.dim_order_status (order_status);
