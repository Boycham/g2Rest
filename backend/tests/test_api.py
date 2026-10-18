from __future__ import annotations

import json
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import DATA_DIR, Settings
from app.main import create_app

TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(token=TOKEN, escalation_sec=0.3, data_dir=DATA_DIR)
    with TestClient(create_app(settings)) as c:
        yield c


def recv(ws, timeout: float = 3.0) -> dict:  # noqa: ANN001
    return json.loads(ws.receive_text())


def test_health_is_open_and_everything_else_needs_the_token(client: TestClient) -> None:
    assert client.get("/health").json()["ok"] is True
    assert client.get("/state").status_code == 401
    assert client.get("/state", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/state", headers=H).status_code == 200
    assert client.get(f"/state?token={TOKEN}").status_code == 200
    assert client.post("/tools/add_item", json={}).status_code == 401


def test_cors_headers_present(client: TestClient) -> None:
    r = client.options(
        "/state",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert r.headers["access-control-allow-origin"] == "*"


def test_ws_rejects_bad_token(client: TestClient) -> None:
    with client.websocket_connect("/ws?token=wrong") as ws:
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_text()
        assert info.value.code == 4401


def test_task_flows_through_the_socket(client: TestClient) -> None:
    with client.websocket_connect(f"/ws?token={TOKEN}&role=server&staff=s1") as ws:
        r = client.post(
            "/tasks",
            headers=H,
            json={
                "kind": "RUN",
                "table": "T2",
                "items": [{"qty": 1, "dish": "soup", "seats": [1]}],
            },
        )
        assert r.status_code == 201
        task_id = r.json()["id"]
        msg = recv(ws)
        assert msg["type"] == "task.assigned" and msg["task"]["state"] == "assigned"
        assert msg["task"]["assignee"] == "s1"
        assert client.get("/tasks", headers=H).json()[0]["backendState"] == "sent"

        ws.send_text(json.dumps({"type": "task.accept", "taskId": task_id}))
        assert recv(ws)["task"]["state"] == "accepted"
        ws.send_text(json.dumps({"type": "task.done", "taskId": task_id}))
        assert recv(ws)["task"]["state"] == "done"

    types = [e["type"] for e in client.get("/events", headers=H).json()]
    assert ["task.queued", "task.sent", "task.accepted", "task.done"] == [
        t for t in types if t.startswith("task.")
    ]


def test_connect_gets_current_state_not_a_replay(client: TestClient) -> None:
    a = client.post("/tasks", headers=H, json={"kind": "CLEAR", "table": "T1"}).json()
    b = client.post("/tasks", headers=H, json={"kind": "CHECK", "table": "T1"}).json()
    client.post(f"/tasks/{a['id']}/done?by={a['assignee']}", headers=H)
    with client.websocket_connect(f"/ws?token={TOKEN}&staff=s1") as ws:
        msg = recv(ws)
        assert msg["task"]["id"] == b["id"]
    with client.websocket_connect(f"/ws?token={TOKEN}&role=manager") as ws:
        assert recv(ws)["type"] == "floor.state"


def test_bounce_and_escalation_over_sockets(client: TestClient) -> None:
    with (
        client.websocket_connect(f"/ws?token={TOKEN}&staff=s1") as s1,
        client.websocket_connect(f"/ws?token={TOKEN}&staff=s2") as s2,
        client.websocket_connect(f"/ws?token={TOKEN}&role=manager&staff=m1") as m1,
    ):
        assert recv(m1)["type"] == "floor.state"
        task = client.post("/tasks", headers=H, json={"kind": "RUN", "table": "T1"}).json()
        assert recv(s1)["task"]["id"] == task["id"]
        s1.send_text(json.dumps({"type": "task.bounce", "taskId": task["id"]}))
        assert recv(s1)["task"]["state"] == "bounced"
        assert recv(s2)["task"]["state"] == "assigned"
        # s2 ignores it; 0.3 s later it escalates to the manager (s1 already tried)
        assert recv(s2)["task"]["state"] == "bounced"
        got = recv(m1)
        assert got["type"] == "task.assigned" and got["task"]["assignee"] == "m1"
        alert = recv(m1)
        assert alert["type"] == "alert" and alert["id"] == f"unacked-{task['id']}"
        m1.send_text(json.dumps({"type": "task.done", "taskId": task["id"]}))
        assert recv(m1)["task"]["state"] == "done"
        assert recv(m1).get("cleared") is True


def test_tools_push_drafts_and_readbacks_then_the_tap_fires(client: TestClient) -> None:
    with client.websocket_connect(f"/ws?token={TOKEN}&staff=s1") as ws:
        ws.send_text(json.dumps({"type": "capture.start", "captureId": "cap-1", "table": "T2"}))
        ws.send_bytes(b"\x00" * 3200)
        ws.send_bytes(b"\x00" * 3200)
        r = client.post(
            "/tools/add_item", headers=H, json={"table": "T2", "seat": 1, "dish": "halibut"}
        ).json()
        assert r["status"] == "ok"
        draft = recv(ws)
        assert draft["type"] == "order.draft" and draft["lines"][0]["dish"] == "Pan-Roasted Halibut"
        bad = client.post(
            "/tools/add_item", headers=H, json={"table": "T2", "seat": 1, "dish": "pizza"}
        )
        assert bad.status_code == 200 and "didYouMean" in bad.json()
        recv(ws)  # draft re-pushed unchanged
        client.post("/tools/confirm_order", headers=H, json={"table": "T2"})
        recv(ws)
        rb = recv(ws)
        assert rb["type"] == "order.readback" and rb["action"] == "confirm"
        ws.send_text(json.dumps({"type": "capture.stop", "captureId": "cap-1"}))
        ws.send_text(json.dumps({"type": "order.confirm", "orderId": r["orderId"]}))
        closed = recv(ws)
        assert closed == {"type": "order.closed", "orderId": r["orderId"], "status": "fired"}
        time.sleep(0.05)
    snap = client.get("/state", headers=H).json()
    assert snap["orders"][0]["status"] == "fired"
    assert snap["captures"][0]["frames"] == 2 and snap["captures"][0]["bytes"] == 6400
    assert next(t for t in snap["tables"] if t["table"] == "T2")["status"] == "ordered"
    assert client.post("/tools/add_item", headers=H, content=b"nope").json()["error"]


def test_reset_clears_runtime_state(client: TestClient) -> None:
    client.post("/tasks", headers=H, json={"kind": "RUN", "table": "T1"})
    assert client.post("/reset", headers=H).json()["ok"]
    assert client.get("/tasks", headers=H).json() == []
    assert client.get("/menu", headers=H).json()["dishes"]
    assert len(client.get("/floor", headers=H).json()["tables"]) == 8


def test_organizer_socket_watches_but_never_counts_as_delivery(client: TestClient) -> None:
    with client.websocket_connect(f"/ws?token={TOKEN}&role=organizer") as org:
        assert org.receive_json()["type"] == "floor.state"
        task = client.post("/tasks", json={"kind": "CLEAR", "table": "T1"}, headers=H).json()
        seen = org.receive_json()
        assert seen["type"] == "task.assigned" and seen["task"]["id"] == task["id"]
        state = client.get("/tasks", headers=H).json()
        assert [t["backendState"] for t in state] == ["queued"]  # s1 is offline: not sent
        with client.websocket_connect(f"/ws?token={TOKEN}&staff=s1") as s1:
            assert s1.receive_json()["task"]["id"] == task["id"]
            state = client.get("/tasks", headers=H).json()
            assert [t["backendState"] for t in state] == ["sent"]


def test_only_the_assignee_can_finish_a_task(client: TestClient) -> None:
    task = client.post("/tasks", headers=H, json={"kind": "CLEAR", "table": "T1"}).json()
    assert client.post(f"/tasks/{task['id']}/done", headers=H).status_code == 422
    assert client.post(f"/tasks/{task['id']}/done?by=organizer", headers=H).status_code == 409
    r = client.post(f"/tasks/{task['id']}/done?by={task['assignee']}", headers=H)
    assert r.status_code == 200 and r.json()["state"] == "done"
