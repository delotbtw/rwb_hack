-- object : mart.dimension_catalog
-- grain  : 1 строка = 1 срез (dim_code)
-- source : справочник; колонки mart.order_summary и mart.v_sales_item
-- cc     : срез допустим для метрики только если его колонка есть в source_view метрики
-- why    : API и агент проверяют допустимость срезов по каталогу, а не по зашитым спискам

CREATE TABLE mart.dimension_catalog (
    dim_code     text PRIMARY KEY,
    name         text NOT NULL,
    column_name  text NOT NULL,
    dim_type     text NOT NULL CHECK (dim_type IN ('categorical', 'time')),
    source_views text[] NOT NULL
);

INSERT INTO mart.dimension_catalog (dim_code, name, column_name, dim_type, source_views) VALUES
    ('month',          'Месяц покупки',     'purchase_month',  'time',        ARRAY['mart.order_summary', 'mart.v_sales_item']),
    ('customer_state', 'Штат покупателя',   'customer_state',  'categorical', ARRAY['mart.order_summary', 'mart.v_sales_item']),
    ('order_status',   'Статус заказа',     'order_status',    'categorical', ARRAY['mart.order_summary', 'mart.v_sales_item']),
    ('seller_state',   'Штат продавца',     'seller_state',    'categorical', ARRAY['mart.v_sales_item']),
    ('seller_id',      'Продавец',          'seller_id',       'categorical', ARRAY['mart.v_sales_item']),
    ('category',       'Категория товара',  'category_label',  'categorical', ARRAY['mart.v_sales_item']);

COMMENT ON TABLE mart.dimension_catalog IS 'Каталог срезов: код, колонка и представления, где срез применим';
