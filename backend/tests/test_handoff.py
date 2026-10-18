"""Handoff (any open task, to a name or the router's pick) and revert (one level of undo)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import DATA_DIR, Settings
from app.main import create_app
from app.tasks import TaskBook, TaskError
from tests.test_tasks import types


def accepted(book: TaskBook, table: str = "T1") -> str:
    task, _ = book.create("CHECK", table, now=0)
    book.mark_sent(task.id, now=1)
    book.accept(task.id, now=2, by="s1")
    return task.id


def test_handoff_an_accepted_task_by_name(book: TaskBook) -> None:
    tid = accepted(book)
    out = book.handoff(tid, now=3, by="s1", to="ben")
    assert types(out) == [("s1", "task.updated", "bounced"), ("s2", "task.assigned", "assigned")]
    with pytest.raises(TaskError, match="no one called Zed"):
        book.handoff(tid, now=4, by="s2", to="Zed")
    with pytest.raises(TaskError, match="already yours"):
        book.handoff(tid, now=4, by="s2", to="s2")
    with pytest.raises(TaskError, match="belongs to s2"):
        book.handoff(tid, now=4, by="s1", to="s1")


def test_revert_accept_and_done(book: TaskBook) -> None:
    tid = accepted(book)
    assert types(book.revert(now=3, by="s1")) == [("s1", "task.updated", "assigned")]
    assert book.get(tid).state == "sent" and book.get(tid).sent_at == 3  # fresh timer
    with pytest.raises(TaskError, match="nothing to revert"):
        book.revert(now=4, by="s1")  # one level only
    book.accept(tid, now=5, by="s1")
    book.done(tid, now=6, by="s1")
    assert types(book.revert(now=7, by="s1")) == [("s1", "task.assigned", "accepted")]
    assert book.get(tid).open


def test_revert_handoff_until_the_new_holder_accepts(book: TaskBook) -> None:
    tid = accepted(book)
    book.handoff(tid, now=3, by="s1", to="s2")
    out = book.revert(now=4, by="s1")
    assert types(out) == [("s2", "task.updated", "bounced"), ("s1", "task.assigned", "accepted")]
    assert book.get(tid).state == "accepted" and book.get(tid).tried == ["s1"]

    book.handoff(tid, now=5, by="s1", to="s2")
    book.mark_sent(tid, now=6)
    book.accept(tid, now=7, by="s2")
    with pytest.raises(TaskError, match="Ben already accepted it"):
        book.revert(now=8, by="s1")


def test_frames_on_the_socket() -> None:
    settings = Settings(token="t", escalation_sec=30, data_dir=DATA_DIR)
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
            ava.send_text(json.dumps({"type": "task.handoff", "taskId": tid}))  # router picks Ben
            assert json.loads(ava.receive_text())["task"]["state"] == "bounced"
            assert json.loads(ben.receive_text())["task"]["assignee"] == "s2"
            ben.send_text(json.dumps({"type": "task.accept", "taskId": tid}))
            assert json.loads(ben.receive_text())["task"]["state"] == "accepted"
            ava.send_text(json.dumps({"type": "task.revert"}))
            assert json.loads(ava.receive_text()) == {
                "type": "task.rejected",
                "taskId": None,
                "action": "revert",
                "reason": "Ben already accepted it",
            }
