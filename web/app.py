"""Streamlit client for the semantic API; no database connection is required."""
import os
from datetime import date

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API = os.getenv("API_BASE_URL", "http://app:8000").rstrip("/")
PAGES = {
    "Продажи": ["revenue", "gmv_with_freight", "orders_total", "avg_check", "units_sold"],
    "Доставка и отзывы": ["late_pct", "avg_delivery_days", "median_delivery_days", "avg_review_score", "reviewed_orders_pct"],
    "Покупатели": ["customers", "repeat_customers_pct"],
}

st.set_page_config(page_title="Capibara Live", layout="wide")


def call(method, path, **kwargs):
    try:
        response = requests.request(method, API + path, timeout=35 if path == "/api/agent" else 10, **kwargs)
        response.raise_for_status()
        return response.json(), None
    except (requests.RequestException, ValueError) as exc:
        detail = str(exc)
        if isinstance(exc, requests.HTTPError):
            try:
                body = exc.response.json()
                detail = body.get("detail") or body.get("error") or detail
            except (ValueError, AttributeError):
                pass
        return None, detail


@st.cache_data(ttl=30, show_spinner=False)
def catalog():
    data, error = call("GET", "/api/metrics")
    if error:
        raise RuntimeError(error)
    return data


def metric_page(page, cat):
    metrics = {m["code"]: m for m in cat.get("metrics", [])}
    available = [code for code in PAGES[page] if code in metrics]
    missing = [code for code in PAGES[page] if code not in metrics]
    if missing:
        st.caption("Нет в каталоге: " + ", ".join(missing))
    if not available:
        st.warning("Для этой страницы метрики пока недоступны в API.")
        return
    code = st.sidebar.selectbox("Метрика", available, format_func=lambda x: metrics[x]["name"])
    metric = metrics[code]
    allowed = metric.get("allowed_dims", [])
    dim_names = {d["code"]: d["name"] for d in cat.get("dimensions", [])}
    with st.sidebar:
        st.subheader("Фильтры")
        date_from = date_to = None
        if "month" in allowed:
            if st.checkbox("Ограничить период"):
                date_from = st.date_input("С даты", date(2017, 1, 1))
                date_to = st.date_input("По дату", date(2018, 12, 31))
        else:
            st.caption("Период для этой метрики недоступен.")
        filters = {}
        for dim, label in [("customer_state", "Штат покупателя"), ("category", "Категория")]:
            if dim in allowed:
                value = st.text_input(label, help="Точное значение из данных; несколько значений через запятую.")
                values = [v.strip() for v in value.split(",") if v.strip()]
                if values:
                    filters[dim] = values[:10]
            else:
                st.caption(f"{label}: срез недоступен для метрики")
        grains = cat.get("grains") or ["month"]
        grain = st.selectbox("Гранула времени", grains, format_func=lambda x: {"day": "День", "week": "Неделя", "month": "Месяц"}.get(x, x), disabled="month" not in allowed)
        group = st.selectbox("Разбивка", [""] + allowed, format_func=lambda x: dim_names.get(x, x) if x else "Без разбивки", index=1 if "month" in allowed and allowed[0] == "month" else 0)
    st.title(page)
    st.subheader(metric["name"])
    if metric.get("description"):
        st.write(metric["description"])
    if metric.get("note"):
        st.caption(metric["note"])
    if date_from and date_to and date_from > date_to:
        st.error("Начало периода позже конца.")
        return
    payload = {"metric": code, "group_by": [group] if group else [], "filters": filters, "grain": grain, "limit": 1000}
    if date_from:
        payload.update(date_from=date_from.isoformat(), date_to=date_to.isoformat())
    data, error = call("POST", "/api/query", json=payload)
    if error:
        st.error(f"Не удалось получить метрику: {error}")
        return
    rows = data.get("rows", [])
    if not rows:
        st.info("Нет данных для выбранных условий.")
        return
    frame = pd.DataFrame(rows)
    if group and group in frame and code in frame:
        fig = px.line(frame, x=group, y=code, markers=True) if group == "month" else px.bar(frame, x=group, y=code)
        fig.update_layout(xaxis_title=dim_names.get(group, group), yaxis_title=f'{metric["name"]} ({metric.get("unit") or ""})')
        selection = st.plotly_chart(fig, use_container_width=True, on_select="rerun", key=f"chart_{code}_{group}")
        points = selection.selection.points
        if points and group != "month":
            selected = points[0].get("x")
            if selected is not None:
                selected_filters = dict(filters)
                selected_value = str(selected)
                if group in selected_filters and selected_value not in selected_filters[group]:
                    st.warning("Выбранная точка не входит в заданный фильтр.")
                    return
                selected_filters[group] = [selected_value]
                detail_payload = dict(payload, group_by=[], filters=selected_filters)
                detail, detail_error = call("POST", "/api/query", json=detail_payload)
                if detail_error:
                    st.warning(f"Не удалось рассчитать выбранный срез: {detail_error}")
                elif detail.get("rows"):
                    value = detail["rows"][0].get(code)
                    st.metric(f"{metric['name']}: {selected}", "Нет данных" if value is None else str(value))
    elif code in frame:
        value = frame.iloc[0][code]
        st.metric(metric["name"], "Нет данных" if pd.isna(value) else f'{value} {metric.get("unit") or ""}')
    st.dataframe(frame, use_container_width=True, hide_index=True)
    if data.get("truncated"):
        st.warning("Показаны первые 1000 строк; результат усечён API.")
    st.download_button("Скачать CSV", frame.to_csv(index=False).encode("utf-8-sig"), f"{code}.csv", "text/csv")
    with st.expander("Как посчитано"):
        st.json(data.get("explain", {}))


@st.fragment(run_every="2s")
def live():
    status, error = call("GET", "/api/status")
    if error:
        st.error(f"Нет связи со статусом API: {error}")
    else:
        stream = status.get("stream") or {}
        cols = st.columns(4)
        for col, label, key in zip(cols, ["Событий/с", "Лаг, событий", "Лаг, с", "Ошибок DLQ"], ["events_per_sec", "lag_events", "lag_sec", "dlq_count"]):
            col.metric(label, stream.get(key, "—"))
        if not stream.get("last_event_ts"):
            st.info("События потока пока не наблюдались. Исторические данные могут быть доступны отдельно.")
        else:
            st.caption(f'Последнее событие: {stream["last_event_ts"]}; обновлено: {stream.get("updated_at") or "—"}')
    orders, error = call("GET", "/api/live/orders")
    st.subheader("Последние заказы")
    if error:
        st.warning(f"Лента заказов недоступна: {error}")
    elif not orders.get("orders"):
        st.info("В ленте пока нет заказов.")
    else:
        st.dataframe(pd.DataFrame(orders["orders"]), use_container_width=True, hide_index=True)


def quality():
    st.title("Качество данных")
    data, error = call("GET", "/api/status")
    if error:
        st.error(f"Статус недоступен: {error}")
        return
    dq = data.get("dq")
    if dq is None:
        st.info("Результаты проверок качества пока недоступны.")
    else:
        st.metric("Проверки DQ", f'{dq.get("passed", "—")} / {dq.get("total", "—")}')
        if dq.get("failed"):
            st.dataframe(pd.DataFrame(dq["failed"]), use_container_width=True, hide_index=True)
    st.subheader("Последняя ночная сборка")
    batch = data.get("last_batch")
    if batch:
        st.json(batch)
    else:
        st.info("Сведений о сборке пока нет.")
    st.subheader("Сверка потока и batch")
    reconcile = data.get("reconcile")
    if reconcile:
        st.write("Совпадает" if reconcile.get("ok") else "Обнаружены расхождения")
        if reconcile.get("items"):
            st.dataframe(pd.DataFrame(reconcile["items"]), use_container_width=True, hide_index=True)
    else:
        st.info("Результаты сверки пока недоступны.")


def render_agent_message(message, index):
    st.markdown(message["content"])
    result = message.get("result") or {}
    chart = result.get("chart") or {}
    chart_frame = pd.DataFrame(chart.get("rows") or [])
    if not chart_frame.empty:
        x, y = chart.get("x"), chart.get("metric")
        chart_type = chart.get("type")
        if not x or x not in chart_frame.columns or y not in chart_frame.columns or chart_type == "table":
            st.dataframe(chart_frame, use_container_width=True, hide_index=True)
        elif chart_type == "pie":
            st.plotly_chart(px.pie(chart_frame, names=x, values=y), use_container_width=True, key=f"agent_chart_{index}")
        elif chart_type in ("bar", "line", "area"):
            fig = {"bar": px.bar, "line": px.line, "area": px.area}[chart_type](chart_frame, x=x, y=y)
            st.plotly_chart(fig, use_container_width=True, key=f"agent_chart_{index}")
        else:
            st.dataframe(chart_frame, use_container_width=True, hide_index=True)
    if result.get("explain"):
        with st.expander("Как посчитано"):
            st.json(result["explain"])


def agent():
    st.title("Спросить агента")
    st.caption("Демо: агент выбирает метрику по словам в вопросе и показывает данные за весь доступный период.")
    for index, message in enumerate(st.session_state.get("messages", [])):
        with st.chat_message(message["role"]):
            render_agent_message(message, index)
    prompt = st.chat_input("Задайте вопрос о данных")
    if prompt:
        user_message = {"role": "user", "content": prompt}
        st.session_state.setdefault("messages", []).append(user_message)
        with st.chat_message("user"):
            render_agent_message(user_message, len(st.session_state.messages) - 1)
        text = prompt.lower()
        choices = [
            (("средн", "чек"), "avg_check", "Средний чек"),
            (("выруч",), "revenue", "Выручка"),
            (("продаж",), "revenue", "Выручка"),
            (("заказ",), "orders_total", "Заказы"),
            (("опозд",), "late_pct", "Доля опозданий"),
            (("достав",), "avg_delivery_days", "Средний срок доставки"),
            (("покупател",), "customers", "Покупатели"),
            (("клиент",), "customers", "Покупатели"),
            (("оплат",), "payments_total", "Сумма оплат"),
            (("платеж",), "payments_total", "Сумма оплат"),
            (("платёж",), "payments_total", "Сумма оплат"),
        ]
        choice = next(((code, name) for words, code, name in choices if all(word in text for word in words)), None)
        if choice:
            code, name = choice
            group = "month" if "месяц" in text else None
            data, error = call("POST", "/api/query", json={"metric": code, "group_by": [group] if group else [], "filters": {}, "limit": 1000})
            if error:
                answer = f"Не удалось получить метрику: {error}"
                result = None
            else:
                answer = f"{name} за весь доступный период. Фильтры из вопроса не применяются."
                result = {"chart": {"type": "line" if group else "table", "x": group, "metric": code, "rows": data.get("rows", [])}, "explain": data.get("explain")}
        else:
            answer = "Попробуйте спросить про выручку, заказы, средний чек, доставку или покупателей."
            result = None
        assistant_message = {"role": "assistant", "content": answer, "result": result}
        st.session_state.messages.append(assistant_message)
        with st.chat_message("assistant"):
            render_agent_message(assistant_message, len(st.session_state.messages) - 1)


page = st.sidebar.radio("Раздел", list(PAGES) + ["Live", "Спросить агента", "Качество данных"])
st.sidebar.caption("Данные предоставляются FastAPI. Live обновляется опросом каждые 2 секунды.")
if page in PAGES:
    try:
        metric_page(page, catalog())
    except RuntimeError as exc:
        st.title(page)
        st.error(f"Каталог метрик недоступен: {exc}")
elif page == "Live":
    st.title("Live")
    live()
elif page == "Спросить агента":
    agent()
else:
    quality()
