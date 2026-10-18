"""Spoken floor requests and table statuses confirmed on the glasses."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from app.config import DATA_DIR, Settings
from app.contract import parse_glasses
from app.main import create_app

H = {"Authorization": "Bearer t"}


def until(ws: Any, match: Any, limit: int = 30) -> dict[str, Any]:
    for _ in range(limit):
        msg = json.loads(ws.receive_text())
        if match(msg):
            return msg
    raise AssertionError("message never came")


def floor_status(msg: dict[str, Any], table: str) -> str | None:
    if msg.get("type") != "floor.state":
        return None
    return next(t["status"] for t in msg["tables"] if t["table"] == table)


def client() -> TestClient:
    return TestClient(create_app(Settings(token="t", escalation_sec=30, data_dir=DATA_DIR)))


def test_frames_are_on_the_contract() -> None:
    assert parse_glasses('{"type":"task.request","table":"T2","kind":"CHECK"}').kind == "CHECK"
    msg = parse_glasses('{"type":"table.status","table":"T5","status":"empty","note":"paid"}')
    assert msg.status == "empty"


def test_table_status_from_glasses_broadcasts_logs_and_creates_the_check() -> None:
    with (
        client() as c,
        c.websocket_connect("/ws?token=t&role=organizer") as org,
        c.websocket_connect("/ws?token=t&role=manager&staff=m1") as mgr,
        c.websocket_connect("/ws?token=t&staff=s1") as ava,
    ):
        ava.send_text(json.dumps({"type": "table.status", "table": "T2", "status": "check"}))
        task = until(org, lambda m: m["type"] == "task.assigned")["task"]
        assert (task["kind"], task["table"]) == ("CHECK", "T2")
        assert until(org, lambda m: floor_status(m, "T2") == "check")
        assert until(mgr, lambda m: floor_status(m, "T2") == "check")  # manager minimap
        # the same status again keeps the one open CHECK
        ava.send_text(json.dumps({"type": "table.status", "table": "T2", "status": "check"}))
        until(org, lambda m: m["type"] == "floor.state")
        checks = [t for t in c.get("/tasks", headers=H).json() if t["kind"] == "CHECK"]
        assert len(checks) == 1
        events = c.get("/events", headers=H).json()
        events = events.get("events", events) if isinstance(events, dict) else events
        set_by = [e for e in events if e["type"] == "table.status" and e["data"].get("by")]
        assert set_by and set_by[-1]["data"] == {"table": "T2", "status": "check", "by": "s1"}


def test_every_status_can_be_set_from_glasses() -> None:
    with (
        client() as c,
        c.websocket_connect("/ws?token=t&role=organizer") as org,
        c.websocket_connect("/ws?token=t&staff=s1") as ava,
    ):
        for status in ("seated", "ordered", "waiting", "eating", "check", "empty"):
            ava.send_text(json.dumps({"type": "table.status", "table": "T4", "status": status}))
            until(org, lambda m, s=status: floor_status(m, "T4") == s)
        ava.send_text(json.dumps({"type": "table.status", "table": "T7", "status": "seated",
                                  "vip": True}))  # fmt: skip
        alert = until(org, lambda m: m["type"] == "alert")
        assert alert["text"] == "VIP seated T7"


def test_task_request_routes_like_post_tasks_and_never_doubles() -> None:
    with (
        client() as c,
        c.websocket_connect("/ws?token=t&role=organizer") as org,
        c.websocket_connect("/ws?token=t&staff=s1") as ava,
    ):
        ava.send_text(json.dumps({"type": "task.request", "table": "T4", "kind": "RUN",
                                  "note": "bread"}))  # fmt: skip
        task = until(org, lambda m: m["type"] == "task.assigned")["task"]
        assert (task["kind"], task["table"], task["notes"]) == ("RUN", "T4", ["bread"])
        assert task["assignee"]
        ava.send_text(json.dumps({"type": "task.request", "table": "T4", "kind": "RUN"}))
        until(org, lambda m: m["type"] == "floor.state")
        assert len([t for t in c.get("/tasks", headers=H).json() if t["kind"] == "RUN"]) == 1


def test_wrong_table_is_rejected_to_the_sender() -> None:
    with client() as c, c.websocket_connect("/ws?token=t&staff=s1") as ava:
        ava.send_text(json.dumps({"type": "task.request", "table": "T12", "kind": "CHECK"}))
        rej = until(ava, lambda m: m["type"] == "task.rejected")
        assert rej["action"] == "request" and "T12" in rej["reason"]
        ava.send_text(json.dumps({"type": "table.status", "table": "T99", "status": "empty"}))
        assert until(ava, lambda m: m["type"] == "task.rejected")["action"] == "status"
        assert c.get("/tasks", headers=H).json() == []
