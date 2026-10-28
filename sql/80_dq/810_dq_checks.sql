-- object : проверки DQ (наполнение mart.dq_result)
-- grain  : 1 INSERT = 1 проверка
-- source : raw.*, core.*, mart.*
-- cc     : DQ-xx из ТЗ §9; контроли Q1–Q5 из tasks.md; инварианты EDA-ноутбука (notebooks/01_*)
-- why    : новая проверка = новая строка в VALUES по этому же шаблону

-- 1. Полнота: ни одна строка raw не потеряна в модели
INSERT INTO mart.dq_result (check_id, description, expected, actual, passed)
SELECT 'DQ-01-' || source_table, 'строк в модели столько же, сколько в raw.' || source_table,
       raw_rows::text, model_rows::text, raw_rows = model_rows
FROM mart.v_layer_rows;

-- 2. Инварианты данных и контроли вопросов
INSERT INTO mart.dq_result (check_id, description, expected, actual, passed)
SELECT check_id, description, expected, actual, expected = actual
FROM (VALUES
    ('DQ-02', 'нет статусов unknown',
     '0', (SELECT COUNT(*)::text FROM core.fact_order WHERE order_status = 'unknown')),
    ('DQ-03', 'заказов без позиций (сохраняются, не удаляются)',
     '775', (SELECT COUNT(*)::text FROM mart.order_summary WHERE NOT has_items)),
    ('DQ-04', 'заказов без оплаты',
     '1', (SELECT COUNT(*)::text FROM mart.order_summary WHERE NOT has_payments)),
    ('DQ-05', 'заказов с несколькими отзывами (все отзывы сохранены)',
     '547', (SELECT COUNT(*)::text FROM mart.order_summary WHERE review_count > 1)),
    ('DQ-06', 'товаров без категории → __unknown__',
     '610', (SELECT COUNT(*)::text FROM core.dim_product WHERE is_missing_category)),
    ('DQ-07', 'категорий без перевода',
     '2', (SELECT COUNT(*)::text FROM core.dim_category WHERE is_untranslated)),
    ('DQ-08', 'расхождений оплаты: всего / больше копейки',
     '639 / 366', (SELECT COUNT(*) FILTER (WHERE reconciliation = 'Расхождение') || ' / '
                       || COUNT(*) FILTER (WHERE ABS(payment_delta) > 0.01) FROM mart.order_summary)),
    ('DQ-09', 'delivered без даты вручения (в продажах есть, в сроках нет)',
     '8', (SELECT COUNT(*)::text FROM mart.order_summary WHERE order_status = 'delivered' AND delivered_customer_at IS NULL)),
    ('DQ-10', 'сумма позиций по заказам = сумме позиций',
     (SELECT SUM(price)::text FROM core.fact_order_item), (SELECT SUM(goods_value)::text FROM mart.order_summary)),
    ('DQ-11', 'сумма оплат по заказам = сумме оплат',
     (SELECT SUM(payment_value)::text FROM core.fact_order_payment), (SELECT SUM(payment_value)::text FROM mart.order_summary)),
    ('DQ-12', 'выручка: по продавцам = по категориям = по месяцам',
     (SELECT SUM(revenue)::text FROM mart.v_sales_month),
     (SELECT CASE WHEN (SELECT SUM(revenue) FROM mart.v_seller_sales) = (SELECT SUM(revenue) FROM mart.v_category_sales)
                  THEN (SELECT SUM(revenue)::text FROM mart.v_seller_sales) ELSE 'не сходится' END)),
    ('Q1-CTRL', 'Q1: 24 месяца, итого выручка',
     '24 / 13221498.11', (SELECT COUNT(*) || ' / ' || SUM(revenue) FROM mart.q01_revenue_by_month)),
    ('Q1-ZERO', 'Q1: один месяц без выручки — 2016-11',
     '2016-11-01', (SELECT string_agg(month::text, ',') FROM mart.q01_revenue_by_month WHERE revenue = 0)),
    ('Q2-CTRL', 'Q2: выручка первого продавца',
     '226987.93', (SELECT revenue::text FROM mart.q02_top_sellers LIMIT 1)),
    ('Q3-CTRL', 'Q3: средний чек заказа',
     '159.88', (SELECT avg_check::text FROM mart.q03_avg_check)),
    ('Q4-CTRL', 'Q4: покупателей / вернулись, %',
     '96096 / 3.12', (SELECT customers || ' / ' || returned_pct FROM mart.q04_repeat_customers)),
    ('Q5-CTRL', 'Q5: категорий / у крупнейшей / сумма',
     '74 / 1233131.72 / 13221498.11',
     (SELECT COUNT(*) || ' / ' || MAX(revenue) || ' / ' || SUM(revenue) FROM mart.q05_revenue_by_category))
) AS t(check_id, description, expected, actual);
