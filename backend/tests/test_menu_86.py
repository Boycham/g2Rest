"""POST /menu/{dish}/86 and /un86: every server and the manager at once, replayed on reconnect."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_api import H, recv


def drain_hello(ws) -> None:  # noqa: ANN001
    """Manager/organizer hello starts with floor.state; open alerts follow it."""
    assert recv(ws)["type"] == "floor.state"


def test_86_reaches_every_server_and_the_manager_and_un86_clears_it(client: TestClient) -> None:
    with (
        client.websocket_connect("/ws?token=test-token&staff=s1") as s1,
        client.websocket_connect("/ws?token=test-token&staff=s2") as s2,
        client.websocket_connect("/ws?token=test-token&role=manager&staff=m1") as m1,
    ):
        drain_hello(m1)
        r = client.post("/menu/halibut/86", headers=H)
        assert r.status_code == 200
        assert r.json() == {"dish": "Pan-Roasted Halibut", "eightySix": ["Pan-Roasted Halibut"]}
        for ws in (s1, s2, m1):
            msg = recv(ws)
            assert (msg["type"], msg["kind"], msg["text"]) == ("alert", "86", "86 halibut")
        assert client.get("/menu/86", headers=H).json() == {"eightySix": ["Pan-Roasted Halibut"]}

        r = client.post("/menu/Pan-Roasted Halibut/un86", headers=H)
        assert r.status_code == 200 and r.json()["eightySix"] == []
        for ws in (s1, s2, m1):
            msg = recv(ws)
            assert (msg["id"], msg["cleared"]) == ("86-halibut", True)


def test_86_needs_the_token_and_a_menu_dish(client: TestClient) -> None:
    assert client.post("/menu/halibut/86").status_code == 401
    r = client.post("/menu/halibutt/86", headers=H)
    assert r.status_code == 404 and "Pan-Roasted Halibut" in r.json()["detail"]
    assert client.post("/menu/halibut/eat", headers=H).status_code == 404


def test_a_reconnecting_server_gets_the_86_list(client: TestClient) -> None:
    client.post("/menu/risotto/86", headers=H)
    client.post("/menu/duck/86", headers=H)
    client.post("/menu/duck/un86", headers=H)
    with client.websocket_connect("/ws?token=test-token&staff=s2") as s2:
        msg = recv(s2)
        assert (msg["id"], msg["text"], msg["kind"]) == ("86-risotto", "86 risotto", "86")
    with client.websocket_connect("/ws?token=test-token&role=manager&staff=m1") as m1:
        drain_hello(m1)
        assert recv(m1)["id"] == "86-risotto"


def test_tool_add_item_on_an_86d_dish_pushes_a_question_line(client: TestClient) -> None:
    client.post("/menu/halibut/86", headers=H)
    with client.websocket_connect("/ws?token=test-token&role=organizer") as org:
        drain_hello(org)
        assert recv(org)["id"] == "86-halibut"  # replayed on connect
        r = client.post(
            "/tools/add_item", json={"table": "T1", "seat": 1, "dish": "halibut"}, headers=H
        )
        assert "86'd" in r.json()["error"]
        draft = recv(org)
        assert draft["type"] == "order.draft" and draft["uncertain"] == ["? s1 halibut 86'd"]


def test_seating_a_vip_party_alerts_the_manager(client: TestClient) -> None:
    with client.websocket_connect("/ws?token=test-token&role=manager&staff=m1") as m1:
        drain_hello(m1)
        r = client.post("/tables/T7/status", json={"status": "seated", "vip": True}, headers=H)
        assert r.status_code == 200
        msg = recv(m1)
        assert (msg["type"], msg["kind"], msg["text"]) == ("alert", "vip", "VIP seated T7")
