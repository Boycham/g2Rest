from __future__ import annotations

import pytest

from app.tasks import TaskBook, TaskError


def types(out: list) -> list[tuple[str, str, str]]:
    return [(o.staff, o.message["type"], o.message["task"]["state"]) for o in out]


def test_happy_path_queued_sent_accepted_done(book: TaskBook) -> None:
    task, out = book.create("RUN", "T2", now=0, items=[{"qty": 2, "dish": "halibut", "seats": [1]}])
    assert task.state == "queued" and task.assignee == "s1"
    assert types(out) == [("s1", "task.assigned", "assigned")]

    book.mark_sent(task.id, now=1)
    assert task.state == "sent"
    assert task.wire()["state"] == "assigned"

    assert types(book.accept(task.id, now=5, by="s1")) == [("s1", "task.updated", "accepted")]
    assert types(book.done(task.id, now=9, by="s1")) == [("s1", "task.updated", "done")]
    assert [h["to"] for h in task.history] == ["queued", "sent", "accepted", "done"]
    assert [e.type for e in book.events.since()] == [
        "task.queued",
        "task.sent",
        "task.accepted",
        "task.done",
    ]


def test_done_allowed_straight_from_sent(book: TaskBook) -> None:
    task, _ = book.create("CLEAR", "T1", now=0)
    book.mark_sent(task.id, now=0)
    book.done(task.id, now=1)
    assert task.state == "done"


def test_illegal_transitions_raise(book: TaskBook) -> None:
    task, _ = book.create("RUN", "T1", now=0)
    book.accept(task.id, now=1)
    with pytest.raises(TaskError):
        book.accept(task.id, now=2)
    with pytest.raises(TaskError):
        book.bounce(task.id, now=2)
    book.done(task.id, now=3)
    with pytest.raises(TaskError):
        book.done(task.id, now=4)
    with pytest.raises(TaskError):
        book.get("nope")


def test_wrong_owner_cannot_act(book: TaskBook) -> None:
    task, _ = book.create("RUN", "T1", now=0)
    with pytest.raises(TaskError):
        book.accept(task.id, now=1, by="s2")


def test_bounce_moves_task_to_next_server_with_same_id(book: TaskBook) -> None:
    task, _ = book.create("RUN", "T1", now=0)
    book.mark_sent(task.id, now=0)
    out = book.bounce(task.id, now=10, by="s1")
    assert types(out) == [("s1", "task.updated", "bounced"), ("s2", "task.assigned", "assigned")]
    assert out[1].message["task"]["id"] == task.id
    assert task.assignee == "s2" and task.state == "queued" and task.tried == ["s1", "s2"]
    assert task.assigned_at == 10


def test_escalates_after_30s_to_next_server_then_manager(book: TaskBook) -> None:
    task, _ = book.create("RUN", "T5", now=0)  # section B: s2 first
    book.mark_sent(task.id, now=0)
    assert book.tick(now=29.9) == []
    out = book.tick(now=30)
    assert types(out) == [("s2", "task.updated", "bounced"), ("s1", "task.assigned", "assigned")]
    assert task.assignee == "s1"

    assert book.tick(now=59) == []
    out = book.tick(now=60)
    assert types(out) == [("s1", "task.updated", "bounced"), ("m1", "task.assigned", "assigned")]
    assert task.assignee == "m1"
    assert [h["to"] for h in task.history] == [
        "queued",
        "sent",
        "escalated",
        "queued",
        "escalated",
        "queued",
    ]


def test_end_of_chain_raises_one_alert_and_done_clears_it(book: TaskBook) -> None:
    task, _ = book.create("RUN", "T1", now=0)
    book.tick(now=30)
    book.tick(now=60)
    assert task.assignee == "m1"
    out = book.tick(now=90)
    assert len(out) == 1 and out[0].staff == "m1"
    alert = out[0].message
    assert alert["type"] == "alert" and alert["level"] == "urgent" and alert["table"] == "T1"
    assert alert["id"] == f"unacked-{task.id}"
    assert book.tick(now=120) == []  # not raised twice
    assert task.assignee == "m1" and task.state == "queued"

    out = book.done(task.id, now=130)
    assert out[1].message == {
        "type": "alert",
        "id": f"unacked-{task.id}",
        "level": "urgent",
        "text": "",
        "table": "T1",
        "sinceSec": 0,
        "cleared": True,
    }


def test_accepted_tasks_never_escalate(book: TaskBook) -> None:
    task, _ = book.create("RUN", "T1", now=0)
    book.accept(task.id, now=1)
    assert book.tick(now=1000) == []
    assert task.assignee == "s1"


def test_open_for_lists_only_that_servers_open_tasks(book: TaskBook) -> None:
    a, _ = book.create("RUN", "T1", now=0)
    b, _ = book.create("RUN", "T5", now=0)
    c, _ = book.create("RUN", "T2", now=0)
    book.done(c.id, now=1)
    assert [t.id for t in book.open_for("s1")] == [a.id]
    assert [t.id for t in book.open_for("s2")] == [b.id]
