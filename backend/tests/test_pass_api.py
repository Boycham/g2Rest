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
        assert recv(org)["type"] == "order.closed"
        # s1 took the order: saw the draft build, then the glasses are told it closed
        s1_seen = [recv(s1)["type"] for _ in range(3)]
        assert s1_seen == ["order.draft", "order.draft", "order.closed"]

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


def busy(client: TestClient, table: str) -> str:
    """Give the table's section server an open RUN task so they are not free."""
    r = client.post("/tasks", json={"kind": "RUN", "table": table}, headers=H)
    assert r.status_code == 201
    return r.json()["id"]


def test_two_hot_courses_pair_because_the_runner_was_busy(client: TestClient) -> None:
    """Live repro: T4 soup then T2 ribeye (both hot, section A) left as two runs. Now the
    first waits while Ava is out, and when she is done both go in one trip."""
    s1_task, _ = busy(client, "T1"), busy(client, "T5")  # s1 and s2 both out on a run
    soup = fire_order(client, "T4", [(1, "soup")])
    ribeye = fire_order(client, "T2", [(1, "ribeye")])
    with client.websocket_connect("/ws?token=test-token&role=organizer&staff=organizer") as org:
        assert recv(org)["type"] == "floor.state"
        state = food_up(client, soup["orderId"], 0).json()
        assert recv(org)["type"] == "pass.state"
        assert [p["status"] for p in state["plates"] if p["table"] == "T4"] == ["up"]
        state = food_up(client, ribeye["orderId"], 0).json()
        assert recv(org)["type"] == "pass.state"
        assert sorted(p["status"] for p in state["plates"]) == ["up", "up"]  # nobody free
        assert state["holds"] == [] and state["runs"] == []
        assert [t["kind"] for t in client.get("/tasks", headers=H).json()] == ["RUN", "RUN"]

        r = client.post(f"/tasks/{s1_task}/done?by=s1", headers=H)
        assert r.status_code == 200
        assert recv(org)["type"] == "task.updated"
        card = recv(org)
        assert card["type"] == "task.assigned" and card["task"]["assignee"] == "s1"
        dishes = [i["dish"] for i in card["task"]["items"]]
        assert dishes == ["Roasted Tomato Soup", "Dry-Aged Ribeye (T2)"]
        assert card["task"]["notes"] == ["T4 appetizers x1, + T2 hot x1", "also T2"]
        state = recv(org)
        assert state["type"] == "pass.state"
        assert [p["status"] for p in state["plates"]] == ["running", "running"]
        run = state["runs"][0]
        assert run["assignees"] == ["s1"] and run["tables"] == ["T4", "T2"]


def test_a_free_server_from_the_other_section_takes_the_run(client: TestClient) -> None:
    busy(client, "T1")  # s1 out
    order = fire_order(client, "T4", [(1, "soup")])
    state = food_up(client, order["orderId"], 0).json()
    assert state["runs"][0]["assignees"] == ["s2"]  # next free server, not the busy section one
    assert [t["assignee"] for t in client.get("/tasks", headers=H).json()][-1] == "s2"


def test_http_cancel_tells_organizers_and_the_glasses(client: TestClient) -> None:
    with (
        client.websocket_connect("/ws?token=test-token&role=organizer&staff=organizer") as org,
        client.websocket_connect("/ws?token=test-token&staff=s1") as s1,
    ):
        assert recv(org)["type"] == "floor.state"
        draft = add(client, "T3", 1, "duck").json()
        assert recv(org)["type"] == "order.draft" and recv(s1)["type"] == "order.draft"
        r = client.post(f"/orders/{draft['orderId']}/cancel", headers=H)
        assert r.status_code == 200 and r.json()["status"] == "cancelled"
        gone = recv(org)
        assert gone["type"] == "order.cancelled" and gone["order"]["orderId"] == draft["orderId"]
        closed = recv(s1)
        assert closed["type"] == "order.closed" and closed["status"] == "cancelled"
        assert closed["orderId"] == draft["orderId"]
