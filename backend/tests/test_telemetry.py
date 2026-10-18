from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk
from fastapi.testclient import TestClient
from sentry_sdk.transport import Transport

from app import telemetry
from app.config import DATA_DIR, Settings
from app.contract import ContractError, parse_glasses
from app.main import create_app

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
INCOMING = f"{TRACE_ID}-00f067aa0ba902b7-1"


def test_task_frames_take_an_optional_trace() -> None:
    plain = parse_glasses(json.dumps({"type": "task.accept", "taskId": "t1"}))
    assert plain.trace is None
    traced = parse_glasses(
        json.dumps({"type": "task.done", "taskId": "t1", "trace": {"sentryTrace": INCOMING}})
    )
    assert traced.trace.sentryTrace == INCOMING
    with pytest.raises(ContractError):
        parse_glasses(json.dumps({"type": "task.accept", "taskId": "t1", "trace": {"x": 1}}))


def test_sentry_is_off_without_a_dsn() -> None:
    assert telemetry.init_sentry("") is False
    assert telemetry.current_trace() is None
    with telemetry.root("task.accept", "noop"), telemetry.span("hub.deliver", "noop"):
        pass


class Capture(Transport):
    """Keeps every transaction in a list instead of sending it."""

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(options)
        self.transactions: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Any) -> None:
        for item in envelope.items:
            if item.type == "transaction":
                self.transactions.append(item.payload.json)


@pytest.fixture
def sent() -> Iterator[list[dict[str, Any]]]:
    capture = Capture()
    assert telemetry.init_sentry("https://public@o0.ingest.example/1", transport=capture)
    yield capture.transactions
    sentry_sdk.get_client().close()
    sentry_sdk.init(dsn=None)


def test_an_organizer_dispatch_and_the_glasses_accept_share_one_trace(
    sent: list[dict[str, Any]],
) -> None:
    app = create_app(Settings(token="t", data_dir=DATA_DIR, trace_wire=True))
    h = {"Authorization": "Bearer t", "sentry-trace": INCOMING}
    with TestClient(app) as client, client.websocket_connect("/ws?token=t&staff=s1") as ws:
        tid = client.post(
            "/tasks", headers=h, json={"kind": "CHECK", "table": "T1", "assignee": "s1"}
        ).json()["id"]
        assigned = json.loads(ws.receive_text())
        assert assigned["trace"]["sentryTrace"].startswith(TRACE_ID)  # proposed §8.11
        ws.send_text(json.dumps({"type": "task.accept", "taskId": tid}))
        assert json.loads(ws.receive_text())["task"]["state"] == "accepted"
        ws.send_text(json.dumps({"type": "task.done", "taskId": tid}))
        assert json.loads(ws.receive_text())["task"]["state"] == "done"
    sentry_sdk.flush()
    by_name = {e["transaction"]: e for e in sent}
    dispatch = by_name["/tasks"]
    assert dispatch["contexts"]["trace"]["trace_id"] == TRACE_ID
    assert {"task.dispatch", "hub.deliver"} <= {s["op"] for s in dispatch["spans"]}
    for name in ("task.accept CHECK T1", "task.done CHECK T1"):
        assert by_name[name]["contexts"]["trace"]["trace_id"] == TRACE_ID
        assert "hub.deliver" in {s["op"] for s in by_name[name]["spans"]}
