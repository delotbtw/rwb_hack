-- object : история категорий и адресов
-- grain  : сущность + момент начала действия
-- source : события product.category_changed, customer.address_changed; контекст заказа
-- cc     : Вброс; прошлые продажи и адрес заказа не подменяются текущими
-- why    : постоянные версии переживают пересборку core/mart

CREATE TABLE IF NOT EXISTS ops.product_category_history (
    seller_id text NOT NULL,
    product_id text NOT NULL,
    valid_from timestamp NOT NULL,
    category_key text NOT NULL,
    event_id uuid NOT NULL UNIQUE,
    PRIMARY KEY (seller_id, product_id, valid_from)
);
CREATE TABLE IF NOT EXISTS ops.customer_address_history (
    customer_unique_id text NOT NULL,
    valid_from timestamp NOT NULL,
    zip_prefix text,
    city text,
    state text,
    event_id uuid NOT NULL UNIQUE,
    PRIMARY KEY (customer_unique_id, valid_from)
);
CREATE TABLE IF NOT EXISTS ops.order_address_snapshot (
    order_id text PRIMARY KEY,
    customer_id text NOT NULL,
    customer_unique_id text NOT NULL,
    purchased_at timestamp NOT NULL,
    zip_prefix text,
    city text,
    state text
);
