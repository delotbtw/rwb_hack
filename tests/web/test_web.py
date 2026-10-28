"""Behavioral checks for the Streamlit client against a stubbed HTTP API."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
requests = pytest.importorskip("requests")
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "web" / "app.py"


class Response:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


@pytest.fixture
def api(monkeypatch):
    calls = []
    responses = {
        "/api/metrics": {
            "metrics": [{"code": "revenue", "name": "Выручка", "allowed_dims": ["month", "customer_state"]}],
            "dimensions": [{"code": "month", "name": "Месяц"}, {"code": "customer_state", "name": "Штат"}],
            "grains": ["month"],
        },
        "/api/query": {"rows": [{"month": "2018-01", "revenue": 125}], "explain": {}},
        "/api/status": {"stream": {"events_per_sec": 4, "lag_events": 2, "lag_sec": 1, "dlq_count": 0, "last_event_ts": "2018-01-01T00:00:00Z"}},
        "/api/live/orders": {"orders": [{"order_id": "order-123", "status": "delivered"}]},
        "/api/agent": {"answer": "Ответ"},
    }

    def request(method, url, **kwargs):
        path = url[url.index("/api/"):]
        calls.append((method, path, kwargs))
        response = responses[path]
        if isinstance(response, Exception):
            raise response
        return Response(response)

    monkeypatch.setattr(requests, "request", request)
    return responses, calls


def app():
    return AppTest.from_file(str(APP), default_timeout=10).run()


def test_extra_catalog_failure_is_visible(api):
    responses, _ = api
    responses["/api/metrics"] = requests.ConnectionError("offline")
    at = app()
    assert not at.exception
    assert any("Каталог метрик недоступен" in e.value and "offline" in e.value for e in at.error)


def test_extra_live_renders_api_status_and_orders(api):
    at = app()
    at.sidebar.radio[0].set_value("Live").run()
    assert not at.exception
    values = {m.label: str(m.value) for m in at.metric}
    assert values == {"Событий/с": "4", "Лаг, событий": "2", "Лаг, с": "1", "Ошибок DLQ": "0"}
    assert at.dataframe[0].value.iloc[0]["order_id"] == "order-123"
    assert any("Последнее событие" in c.value for c in at.caption)


def test_extra_live_handles_both_api_failures(api):
    responses, _ = api
    responses["/api/status"] = requests.ConnectionError("status offline")
    responses["/api/live/orders"] = requests.ConnectionError("orders offline")
    at = app()
    at.sidebar.radio[0].set_value("Live").run()
    assert not at.exception
    assert any("status offline" in e.value for e in at.error)
    assert any("orders offline" in e.value for e in at.warning)


def test_extra_filters_only_send_allowed_dimensions(api):
    _, calls = api
    at = app()
    assert not at.exception
    assert [widget.label for widget in at.text_input] == ["Штат покупателя"]
    at.text_input[0].set_value(" SP, RJ ").run()
    payload = [kwargs["json"] for _, path, kwargs in calls if path == "/api/query"][-1]
    assert payload["filters"] == {"customer_state": ["SP", "RJ"]}
    assert set(payload["group_by"]) <= {"month", "customer_state"}








def test_extra_chart_selection_cannot_expand_existing_filter(api, monkeypatch):
    from types import SimpleNamespace
    import streamlit as st

    responses, calls = api
    responses["/api/query"] = {"rows": [{"customer_state": "RJ", "revenue": 125}]}
    monkeypatch.setattr(st, "plotly_chart", lambda *args, **kwargs: SimpleNamespace(
        selection=SimpleNamespace(points=[{"x": "RJ"}])
    ))
    at = app()
    at.text_input[0].set_value("SP").run()
    at.selectbox[2].set_value("customer_state").run()
    assert not at.exception
    assert any("не входит в заданный фильтр" in warning.value for warning in at.warning)
    filtered = [kwargs["json"] for _, path, kwargs in calls if path == "/api/query" and kwargs["json"]["filters"]]
    assert filtered
    assert all(payload["filters"]["customer_state"] == ["SP"] for payload in filtered)


