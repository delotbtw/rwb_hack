-- object : mart.v_product_price_item, mart.v_product_price_history
-- grain  : позиция; день + цена выбранного товара
-- source : core.fact_order_item, core.fact_order
-- cc     : Q6–Q10; независимые факты не размножаются
-- why    : определения нового ноутбука без изменения Q1–Q5

CREATE VIEW mart.v_product_price_item AS
SELECT i.*, o.purchased_at AS purchase_ts,
       date_trunc('month', o.purchased_at)::date AS purchase_month, o.order_status
FROM core.fact_order_item i
LEFT JOIN core.fact_order o ON o.order_id = i.order_id;

CREATE VIEW mart.v_product_price_history AS
WITH chosen AS (
    SELECT product_id FROM mart.v_product_price_item
    GROUP BY product_id ORDER BY COUNT(DISTINCT price) DESC, product_id LIMIT 1
)
SELECT p.product_id, p.purchase_ts::date AS purchase_date, p.price, COUNT(*) AS units
FROM mart.v_product_price_item p
LEFT JOIN chosen c ON c.product_id = p.product_id
WHERE c.product_id IS NOT NULL
GROUP BY p.product_id, p.purchase_ts::date, p.price;
