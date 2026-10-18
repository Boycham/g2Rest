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

    book.mark_sent(task.id, now=30)
    assert book.tick(now=59) == []
    out = book.tick(now=60)
    assert types(out) == [("s1", "task.updated", "bounced"), ("m1", "task.assigned", "assigned")]
    assert task.assignee == "m1"
    assert [h["to"] for h in task.history] == [
        "queued",
        "sent",
        "escalated",
        "queued",
        "sent",
        "escalated",
        "queued",
    ]


def test_end_of_chain_raises_one_alert_and_done_clears_it(book: TaskBook) -> None:
    task, _ = book.create("RUN", "T1", now=0)
    for t in (0, 30, 60):  # each new assignee's card is delivered at once
        book.mark_sent(task.id, now=t)
        out = book.tick(now=t + 30)
    assert task.assignee == "m1"
    assert len(out) == 1 and out[0].staff == "m1"
    alert = out[0].message
    assert alert["type"] == "alert" and alert["level"] == "urgent" and alert["table"] == "T1"
    assert alert["id"] == f"unacked-{task.id}"
    assert book.tick(now=120) == []  # not raised twice
    assert task.assignee == "m1" and task.state == "sent"

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


def test_escalation_timer_starts_at_sent_not_at_creation(book: TaskBook) -> None:
    task, _ = book.create("RUN", "T1", now=0)
    assert book.tick(now=100) == []  # queued: assignee offline, only the 2 min timer runs
    book.mark_sent(task.id, now=100)
    assert book.tick(now=129) == []
    assert types(book.tick(now=130)) == [
        ("s1", "task.updated", "bounced"),
        ("s2", "task.assigned", "assigned"),
    ]
    assert task.state == "queued" and task.sent_at is None  # s2's timer waits for delivery


def test_escalation_timer_stops_at_accepted(book: TaskBook) -> None:
    task, _ = book.create("RUN", "T1", now=0)
    book.mark_sent(task.id, now=0)
    book.accept(task.id, now=29)
    assert book.tick(now=10_000) == []
    assert task.state == "accepted"


def test_task_queued_for_an_offline_server_escalates_after_two_minutes(book: TaskBook) -> None:
    task, _ = book.create("RUN", "T1", now=0)
    assert book.tick(now=119.9) == []
    assert types(book.tick(now=120)) == [
        ("s1", "task.updated", "bounced"),
        ("s2", "task.assigned", "assigned"),
    ]
    assert task.state == "queued" and task.assignee == "s2"
    assert book.tick(now=239.9) == []  # s2 offline too: its own 2 min from reassignment
    assert types(book.tick(now=240)) == [
        ("s2", "task.updated", "bounced"),
        ("m1", "task.assigned", "assigned"),
    ]
    out = book.tick(now=360)  # end of the chain: the manager gets the alert
    assert [(o.staff, o.message["type"]) for o in out] == [("m1", "alert")]


def test_unaccept_puts_an_accepted_task_back_for_its_owner_only(book: TaskBook) -> None:
    task, _ = book.create("RUN", "T2", now=0)
    book.mark_sent(task.id, now=1)
    book.accept(task.id, now=2, by="s1")
    with pytest.raises(TaskError):
        book.unaccept(task.id, now=3, by="s2")
    assert types(book.unaccept(task.id, now=4, by="s1")) == [("s1", "task.updated", "assigned")]
    assert task.state == "sent" and task.sent_at == 4
    with pytest.raises(TaskError):
        book.unaccept(task.id, now=5, by="s1")
