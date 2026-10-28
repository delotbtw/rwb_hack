"""API /api/query (K1-T6, A-1, A-2). Без БД или роли app_ro тесты пропускаются."""

from __future__ import annotations

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.api.db import connect_ro
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    try:
        with connect_ro():
            pass
    except psycopg2.Error as exc:
        pytest.skip(f"database or app_ro role is not available: {type(exc).__name__}")
    return TestClient(app)


def test_query_revenue_total(client):
    resp = client.post("/api/query", json={"metric": "revenue"})
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert len(rows) == 1
    assert abs(float(rows[0]["revenue"]) - 13221498.11) < 0.005


def test_query_unknown_metric(client):
    resp = client.post("/api/query", json={"metric": "nope"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "unknown_metric"
    assert "revenue" in body["allowed"]
