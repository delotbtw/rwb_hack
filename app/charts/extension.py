"""Ответы Q6–Q10 из SQL-модели; чтение без изменения данных и кэша снимка."""

from datetime import date, datetime
from decimal import Decimal


PAYMENTS = """
SELECT {grouping}, COUNT(*) AS payment_count, SUM(payment_value) AS amount,
       AVG(payment_installments) AS mean_installments
FROM mart.v_payment_context {where}
GROUP BY {grouping} ORDER BY {grouping}
"""
YEAR_2018 = "WHERE purchase_ts >= '2018-01-01' AND purchase_ts < '2019-01-01'"

# Только фиксированные запросы: пользовательские значения в SQL не подставляются.
TABLES = (
    ("Q6. История наблюдаемых цен", "Дата — день покупки; число единиц равно числу позиций. Товар выбран по максимуму разных цен во всех статусах.",
     "SELECT product_id, purchase_date, price, units FROM mart.v_product_price_history ORDER BY purchase_date, price"),
    ("Q7. Доставка по штатам", "Порог 500 применяется к валидным delivered-заказам; опоздание считается по календарному дню.",
     "SELECT customer_state, valid_orders, mean_delivery_days, late_pct FROM mart.v_delivery_by_state WHERE valid_orders >= 500 ORDER BY customer_state"),
    ("Q7. Покрытие всех штатов", "Все заказы и число заказов с валидными датами, включая штаты ниже порога.",
     "SELECT customer_state, all_orders, valid_orders FROM mart.v_delivery_by_state ORDER BY customer_state"),
    ("Q8. Итоговые статусы заказов", "Распределение статусов снимка; колонка without_items показывает заказы без позиций.",
     "SELECT order_status, orders, share_pct, without_items FROM mart.v_order_status_snapshot ORDER BY orders DESC, order_status"),
    ("Q9. Оплаты по штатам за 2018 год", "Год определяется датой покупки заказа. Все статусы; одна строка источника — платёжная запись.",
     PAYMENTS.format(grouping="customer_state", where=YEAR_2018)),
    ("Q9. Способы оплаты за весь период", "Среднее число частей оплаты включает исходные нули; сумма не умножается на число частей.",
     PAYMENTS.format(grouping="payment_type", where="")),
    ("Q9. Способы оплаты за 2018 год", "Дополнительный разрез по дате покупки заказа, все статусы.",
     PAYMENTS.format(grouping="payment_type", where=YEAR_2018)),
    ("Q10. Выбранная оценка и доставка", "Один последний выбранный отзыв на заказ; только валидные доставки. Неизвестное среднее — прочерк, не ноль.",
     "SELECT score, orders, mean_delivery_days, late_pct FROM mart.v_review_delivery_summary ORDER BY score"),
)

LABELS = {
    "product_id": "Товар", "purchase_date": "Дата", "price": "Цена, BRL", "units": "Единиц",
    "customer_state": "Штат", "valid_orders": "Валидных заказов", "all_orders": "Всего заказов",
    "mean_delivery_days": "Средний срок, дни", "late_pct": "Опозданий, %",
    "order_status": "Статус", "orders": "Заказов", "share_pct": "Доля, %",
    "without_items": "Без позиций", "payment_count": "Платежей", "amount": "Сумма, BRL",
    "mean_installments": "Среднее число частей оплаты", "payment_type": "Способ оплаты", "score": "Оценка",
}


def _display(value):
    if value is None:
        return "—"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (Decimal, float)):
        return f"{value:,.3f}".replace(",", " ")
    return str(value)


def load_tables(conn):
    """Свежие агрегаты на каждый запрос страницы, в том числе после событий потока."""
    result = []
    with conn.cursor() as cur:
        for title, caption, query in TABLES:
            cur.execute(query)
            columns = [LABELS.get(column.name, column.name) for column in cur.description]
            result.append({"title": title, "caption": caption, "columns": columns,
                           "rows": [[_display(value) for value in row] for row in cur.fetchall()]})
    return result
