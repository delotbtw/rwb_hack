"""Contract tests for the read-only live orders endpoint."""

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def db(monkeypatch):
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        ("order-1", datetime(2020, 1, 2, 3, 4, 5), "delivered", "SP", Decimal("12.50")),
        ("order-2", None, "created", None, None),
    ]
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    @contextmanager
    def connect():
        yield connection

    monkeypatch.setattr("app.api.routes.connect_ro", connect)
    return cursor


def test_live_orders_contract_and_query(db):
    response = TestClient(app).get("/api/live/orders")
    assert response.status_code == 200
    assert response.json() == {"orders": [
        {"order_id": "order-1", "purchased_at": "2020-01-02T03:04:05",
         "order_status": "delivered", "customer_state": "SP", "order_value": "12.50"},
        {"order_id": "order-2", "purchased_at": None, "order_status": "created",
         "customer_state": None, "order_value": None},
    ]}
    sql, params = db.execute.call_args.args
    assert "FROM mart.order_summary" in sql
    assert "ORDER BY purchased_at DESC NULLS LAST, order_id" in sql
    assert params == (20,)


@pytest.mark.parametrize("limit, expected", [(1, 1), (20, 20), (100, 20)])
def test_live_orders_limit(db, limit, expected):
    response = TestClient(app).get("/api/live/orders", params={"limit": limit})
    assert response.status_code == 200
    assert db.execute.call_args.args[1] == (expected,)


@pytest.mark.parametrize("limit", [0, 101, "invalid"])
def test_live_orders_invalid_limit(db, limit):
    response = TestClient(app).get("/api/live/orders", params={"limit": limit})
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"
    db.execute.assert_not_called()
