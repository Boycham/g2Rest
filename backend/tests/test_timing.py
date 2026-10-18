"""How long each server takes, and the done timer that reroutes a task held too long."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.config import DATA_DIR, Settings
from app.data import Floor
from app.events import EventLog
from app.main import create_app
from app.tasks import TaskBook
from tests.test_tasks import types


def accepted(book: TaskBook, kind: str = "CHECK") -> str:
    task, _ = book.create(kind, "T1", now=0)  # T1 is Ava's (s1)
    book.mark_sent(task.id, now=1)
    book.accept(task.id, now=2, by="s1")
    return task.id


def test_stats_average_accept_to_done(book: TaskBook) -> None:
    book.done(accepted(book), now=62, by="s1")
    open_id = accepted(book, "CLEAR")
    ava = book.stats(now=32)[0]
    assert (ava["done"], ava["avgSec"], ava["avgSecByKind"]) == (1, 60, {"CHECK": 60})
    assert ava["open"] == [
        {"taskId": open_id, "kind": "CLEAR", "table": "T1", "state": "accepted", "heldSec": 30}
    ]
    assert book.stats(now=32)[1]["avgSec"] is None  # Ben has done nothing yet


def test_held_too_long_alerts_the_manager_and_moves_the_task(floor: Floor) -> None:
    book = TaskBook(floor, EventLog(), done_sec=300)
    tid = accepted(book)
    assert book.overdue(now=301) == []
    out = book.reroute(tid, now=302, to="s2")
    assert out[0].staff == "m1" and out[0].message["text"] == "T1 check: Ava 5:00, moved to Ben"
    assert types(out[1:]) == [
        ("s1", "task.updated", "bounced"),
        ("s2", "task.assigned", "assigned"),
    ]
    assert book.overdue(now=900) == [] and book.reroute(tid, now=900, to="s1") == []
    book.mark_sent(tid, now=903)
    book.accept(tid, now=904, by="s2")
    cleared = book.done(tid, now=905, by="s2")[-1].message
    assert cleared["id"] == f"slow-{tid}" and cleared["cleared"] is True


def test_a_run_is_never_moved_only_flagged(floor: Floor) -> None:
    book = TaskBook(floor, EventLog(), done_sec=300)
    tid = accepted(book, "RUN")
    out = book.reroute(tid, now=302, to="s2")
    assert [o.message["text"] for o in out] == ["T1 run: Ava 5:00"]
    assert book.get(tid).assignee == "s1" and book.overdue(now=400) == []


def test_the_ticker_reroutes_and_stats_are_served() -> None:
    settings = Settings(token="t", escalation_sec=30, done_sec=0.5, data_dir=DATA_DIR)
    with TestClient(create_app(settings)) as client:
        h = {"Authorization": "Bearer t"}
        with (
            client.websocket_connect("/ws?token=t&staff=s1") as ava,
            client.websocket_connect("/ws?token=t&staff=s2") as ben,
        ):
            tid = client.post("/tasks", headers=h, json={"kind": "CHECK", "table": "T1"}).json()[
                "id"
            ]
            assert json.loads(ava.receive_text())["type"] == "task.assigned"
            ava.send_text(json.dumps({"type": "task.accept", "taskId": tid}))
            assert json.loads(ava.receive_text())["task"]["state"] == "accepted"
            assert json.loads(ava.receive_text())["task"]["state"] == "bounced"  # within ~1.5 s
            assert json.loads(ben.receive_text())["task"]["id"] == tid
        stats = client.get("/stats", headers=h).json()
        assert stats["doneSec"] == 0.5
        assert stats["escalationSec"] == 30
        assert [s["open"][0]["taskId"] for s in stats["servers"] if s["open"]] == [tid]
