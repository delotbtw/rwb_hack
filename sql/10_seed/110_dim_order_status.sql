-- object : core.dim_order_status
-- grain  : 1 строка = 1 статус заказа
-- source : статический справочник (8 статусов из handout.md) + unknown-member
-- cc     : FR-30 (определение выручки)
-- why    : определение выручки меняется флагом здесь, а не в каждом запросе

CREATE TABLE core.dim_order_status (
    order_status text PRIMARY KEY,
    is_revenue   boolean NOT NULL,
    is_final     boolean NOT NULL,
    description  text NOT NULL
);

INSERT INTO core.dim_order_status (order_status, is_revenue, is_final, description) VALUES
    ('delivered',   true,  true,  'вручён покупателю'),
    ('shipped',     false, false, 'передан в доставку'),
    ('canceled',    false, true,  'отменён'),
    ('unavailable', false, true,  'недоступен'),
    ('invoiced',    false, false, 'выставлен счёт'),
    ('processing',  false, false, 'в обработке'),
    ('created',     false, false, 'создан'),
    ('approved',    false, false, 'оплата подтверждена'),
    ('unknown',     false, false, 'unknown-member: статус не распознан');
