-- object : история категорий и адресов
-- grain  : сущность + момент начала действия
-- source : события product.category_changed, customer.address_changed; контекст заказа
-- cc     : Вброс; прошлые продажи и адрес заказа не подменяются текущими
-- why    : постоянные версии переживают пересборку core/mart

GRANT SELECT, INSERT, UPDATE ON ops.product_category_history TO ingestor;
GRANT SELECT, INSERT, UPDATE ON ops.customer_address_history TO ingestor;
GRANT SELECT, INSERT ON ops.order_address_snapshot TO ingestor;
