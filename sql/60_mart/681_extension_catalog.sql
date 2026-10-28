-- object : mart.metric_catalog, mart.dimension_catalog
-- grain  : метрика; срез
-- source : справочник
-- cc     : Q6–Q10; независимые факты не размножаются
-- why    : определения нового ноутбука без изменения Q1–Q5

UPDATE mart.dimension_catalog SET source_views = source_views || ARRAY['mart.v_product_price_item','mart.v_payment_context','mart.v_review_delivery'] WHERE dim_code = 'month';
UPDATE mart.dimension_catalog SET source_views = source_views || ARRAY['mart.v_payment_context','mart.v_review_delivery'] WHERE dim_code = 'customer_state';
UPDATE mart.dimension_catalog SET source_views = source_views || ARRAY['mart.v_product_price_item','mart.v_payment_context'] WHERE dim_code = 'order_status';
UPDATE mart.dimension_catalog SET source_views = source_views || ARRAY['mart.v_product_price_item'] WHERE dim_code = 'seller_id';
INSERT INTO mart.dimension_catalog VALUES
('product','Товар','product_id','categorical',ARRAY['mart.v_product_price_item']),
('payment_type','Способ оплаты','payment_type','categorical',ARRAY['mart.v_payment_context']),
('review_score','Выбранная оценка','review_score','categorical',ARRAY['mart.v_review_delivery']);
INSERT INTO mart.metric_catalog
(metric_code,name,description,formula_sql,source_view,grain,additivity,unit,allowed_dims,note) VALUES
('observed_price_count','Различных наблюдаемых цен','Различных наблюдаемых цен','COUNT(DISTINCT price)','mart.v_product_price_item','позиция','non','count',ARRAY['month','product','seller_id','order_status'],'Q6–Q10: правила расчёта зафиксированы в docs/decisions.md'),
('observed_units','Позиций по всем статусам','Позиций по всем статусам','COUNT(*)','mart.v_product_price_item','позиция','additive','count',ARRAY['month','product','seller_id','order_status'],'Q6–Q10: правила расчёта зафиксированы в docs/decisions.md'),
('observed_avg_price','Средняя наблюдаемая цена','Средняя наблюдаемая цена','AVG(price)','mart.v_product_price_item','позиция','non','BRL',ARRAY['month','product','seller_id','order_status'],'Q6–Q10: правила расчёта зафиксированы в docs/decisions.md'),
('valid_delivery_orders','Заказы с валидной доставкой','Заказы с валидной доставкой','COUNT(*) FILTER (WHERE is_valid_delivery)','mart.order_summary','заказ','additive','count',ARRAY['month','customer_state','order_status'],'Q6–Q10: правила расчёта зафиксированы в docs/decisions.md'),
('orders_without_items','Заказы без позиций','Заказы без позиций','COUNT(*) FILTER (WHERE NOT has_items)','mart.order_summary','заказ','additive','count',ARRAY['month','customer_state','order_status'],'Q6–Q10: правила расчёта зафиксированы в docs/decisions.md'),
('payment_records','Платёжные записи','Платёжные записи','COUNT(*)','mart.v_payment_context','платёж','additive','count',ARRAY['month','customer_state','order_status','payment_type'],'Q6–Q10: правила расчёта зафиксированы в docs/decisions.md'),
('payments_all_statuses','Сумма оплат по всем статусам','Сумма оплат по всем статусам','SUM(payment_value)','mart.v_payment_context','платёж','additive','BRL',ARRAY['month','customer_state','order_status','payment_type'],'Q6–Q10: правила расчёта зафиксированы в docs/decisions.md'),
('mean_installments','Среднее число частей оплаты','Среднее число частей оплаты','AVG(payment_installments)','mart.v_payment_context','платёж','non','count',ARRAY['month','customer_state','order_status','payment_type'],'Q6–Q10: правила расчёта зафиксированы в docs/decisions.md'),
('rated_delivery_orders','Доставки с выбранным отзывом','Доставки с выбранным отзывом','COUNT(*) FILTER (WHERE review_score IS NOT NULL)','mart.v_review_delivery','заказ','additive','count',ARRAY['month','customer_state','review_score'],'Q6–Q10: правила расчёта зафиксированы в docs/decisions.md'),
('rated_mean_delivery_days','Средний срок по выбранной оценке','Средний срок по выбранной оценке','AVG(delivery_days) FILTER (WHERE review_score IS NOT NULL)','mart.v_review_delivery','заказ','non','days',ARRAY['month','customer_state','review_score'],'Q6–Q10: правила расчёта зафиксированы в docs/decisions.md'),
('rated_late_pct','Доля опозданий по выбранной оценке','Доля опозданий по выбранной оценке','100.0 * COUNT(*) FILTER (WHERE review_score IS NOT NULL AND delay_days > 0) / NULLIF(COUNT(*) FILTER (WHERE review_score IS NOT NULL),0)','mart.v_review_delivery','заказ','non','pct',ARRAY['month','customer_state','review_score'],'Q6–Q10: правила расчёта зафиксированы в docs/decisions.md');
