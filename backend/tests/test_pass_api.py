"""Kitchen 'food up' endpoints: POST /pass/up, GET /pass, pass.state and order.fired broadcasts."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.test_api import H, recv


def food_up(client: TestClient, order_id: str, line: int) -> Any:
    return client.post("/pass/up", json={"orderId": order_id, "line": line}, headers=H)


def add(client: TestClient, table: str, seat: int, dish: str) -> Any:
    body = {"table": table, "seat": seat, "dish": dish}
    return client.post("/tools/add_item", json=body, headers=H)


def fire_order(client: TestClient, table: str, dishes: list[tuple[int, str]]) -> dict[str, Any]:
    order_id = ""
    for seat, dish in dishes:
        r = add(client, table, seat, dish)
        assert r.status_code == 200 and r.json()["status"] == "ok", r.text
        order_id = r.json()["orderId"]
    r = client.post(f"/orders/{order_id}/confirm", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "fired"
    return r.json()


def test_food_up_runs_the_engine_and_dispatches_a_run_task(client: TestClient) -> None:
    with (
        client.websocket_connect("/ws?token=test-token&role=organizer") as org,
        client.websocket_connect("/ws?token=test-token&staff=s1") as s1,
    ):
        assert recv(org)["type"] == "floor.state"
        order = fire_order(client, "T1", [(1, "ribeye"), (2, "nicoise")])
        seen = []
        while not seen or seen[-1] != "pass.state":
            seen.append(recv(org)["type"])
        assert seen[-3:] == ["floor.state", "order.fired", "pass.state"]
        assert "order.draft" in seen  # organizers also watch every draft
        assert [recv(s1)["type"] for _ in range(2)] == ["order.draft"] * 2  # s1 took the order

        before = client.get("/pass", headers=H).json()
        assert [p["status"] for p in before["plates"]] == ["waiting", "waiting"]
        assert {p["line"] for p in before["plates"]} == {0, 1}
        assert before["holds"] == [
            {"table": "T1", "course": "main", "waitingOn": ["Dry-Aged Ribeye", "Nicoise Salad"]}
        ]

        r = food_up(client, order["orderId"], 0)
        assert r.status_code == 200
        state = r.json()
        assert state["holds"] == [{"table": "T1", "course": "main", "waitingOn": ["Nicoise Salad"]}]
        up = next(p for p in state["plates"] if p["line"] == 0)
        assert up["status"] == "up" and up["plateId"] == f"{order['orderId']}:0"
        assert up["dish"] == "Dry-Aged Ribeye" and up["temperature"] == "hot" and up["score"] > 0
        assert recv(org)["type"] == "pass.state"
        assert client.get("/tasks", headers=H).json() == []  # the course is held

        r = food_up(client, order["orderId"], 1)
        assert r.status_code == 200
        assert [p["status"] for p in r.json()["plates"]] == ["running", "running"]
        assert r.json()["holds"] == []
        assert r.json()["runs"][0]["tables"] == ["T1"]

        card = recv(s1)
        assert card["type"] == "task.assigned" and card["task"]["kind"] == "RUN"
        assert card["task"]["table"] == "T1"
        assert [i["dish"] for i in card["task"]["items"]] == ["Dry-Aged Ribeye", "Nicoise Salad"]
        assert [i["seats"] for i in card["task"]["items"]] == [[1], [2]]
        assert card["task"]["notes"] == ["T1 mains x2"]
        assert recv(org)["type"] == "task.assigned"  # organizers watch every card
        assert recv(org)["type"] == "pass.state"

    types = [e["type"] for e in client.get("/events", headers=H).json()]
    assert ["pass.ticket", "pass.up", "pass.up", "pass.run"] == [
        t for t in types if t.startswith("pass.")
    ]


def test_food_up_conflicts(client: TestClient) -> None:
    order = fire_order(client, "T2", [(1, "soup")])
    oid = order["orderId"]
    assert food_up(client, "nope", 0).status_code == 409
    assert food_up(client, oid, 5).status_code == 409
    assert food_up(client, oid, 0).status_code == 200
    r = food_up(client, oid, 0)
    assert r.status_code == 409 and "already up" in r.json()["detail"]
    # a draft (not fired) order has no plates at the pass
    draft = add(client, "T3", 1, "duck")
    draft_id = draft.json()["orderId"]
    assert food_up(client, draft_id, 0).status_code == 409
    assert food_up(client, oid, -1).status_code == 422


def test_bigger_course_creates_a_second_runner_task(client: TestClient) -> None:
    order = fire_order(client, "T5", [(i + 1, "salmon") for i in range(4)])
    for line in range(4):
        r = food_up(client, order["orderId"], line)
        assert r.status_code == 200
    tasks = client.get("/tasks", headers=H).json()
    assert [(t["assignee"], len(t["items"])) for t in tasks] == [("s2", 3), ("s1", 1)]
    assert tasks[1]["notes"][0].startswith("runner 2 of 2")


def test_planner_switch_to_fifo(client: TestClient) -> None:
    r = client.post("/pass/planner", json={"planner": "fifo"}, headers=H)
    assert r.status_code == 200 and r.json()["weights"]["course_weight"] == 4.0
    order = fire_order(client, "T1", [(1, "ribeye"), (2, "nicoise")])
    r = food_up(client, order["orderId"], 0)
    assert r.json()["planner"] == "fifo"
    by_line = {p["line"]: p["status"] for p in r.json()["plates"]}
    assert by_line == {0: "running", 1: "waiting"}  # no course hold in the baseline
    assert client.post("/pass/planner", json={"planner": "lifo"}, headers=H).status_code == 422
