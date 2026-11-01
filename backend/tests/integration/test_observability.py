import io
import json
import logging
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers import Api, equal

LogLines = Callable[[], list[dict[str, Any]]]


@pytest.fixture
def log_lines(app: FastAPI) -> Iterator[LogLines]:
    """Point the app's JSON log handler at a buffer and turn INFO events on."""
    root = logging.getLogger()
    (handler,) = root.handlers
    assert isinstance(handler, logging.StreamHandler)
    buffer = io.StringIO()
    previous_stream, previous_level = handler.setStream(buffer), root.level
    root.setLevel(logging.INFO)

    def read() -> list[dict[str, Any]]:
        return [json.loads(line) for line in buffer.getvalue().splitlines()]

    yield read
    root.setLevel(previous_level)
    handler.setStream(previous_stream)


def test_domain_events_are_json_lines_correlated_by_request_id(
    client: TestClient, api: Api, log_lines: LogLines
) -> None:
    ada, bob = api.register(), api.register()
    group_id = api.create_group(ada, bob)
    api.add_expense(ada, group_id, paid_by=ada.id, amount_cents=100, split=equal(bob.id))

    response = client.post(
        f"/api/groups/{group_id}/settlements",
        json={"payer_id": bob.id, "payee_id": ada.id, "amount_cents": 100},
        headers={**bob.headers, "Idempotency-Key": "k", "X-Request-ID": "req-42"},
    )
    assert response.status_code == 201

    lines = [line for line in log_lines() if line.get("request_id") == "req-42"]
    created = next(line for line in lines if line["event"] == "settlement.created")
    access = next(line for line in lines if line["event"] == "http.request")
    assert created["settlement_id"] == response.json()["id"]
    assert created["amount_cents"] == 100
    assert (access["method"], access["status"]) == ("POST", 201)
    assert access["duration_ms"] >= 0


def test_unhandled_error_is_a_500_envelope_and_is_logged_with_traceback(
    app: FastAPI, log_lines: LogLines
) -> None:
    def explode() -> None:
        raise RuntimeError("boom")

    app.add_api_route("/api/explode", explode)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/explode", headers={"X-Request-ID": "req-500"})

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error"}
    }
    logged = next(line for line in log_lines() if line.get("status") == 500)
    assert logged["request_id"] == "req-500"
    assert logged["level"] == "ERROR"
    assert "RuntimeError: boom" in logged["exc"]
