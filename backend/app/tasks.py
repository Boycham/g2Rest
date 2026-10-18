"""Task state machine: queued -> sent -> accepted -> done, with bounce and escalation.

Pure and clock-free: callers pass `now` (seconds, any monotonic source) and `tick(now)`
performs escalations. Every transition returns `Outbound` messages for the hub to deliver
and appends to the event log, so the hub, the tests and the walkthrough script all see
the same thing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.data import Floor
from app.events import EventLog

TaskState = Literal["queued", "sent", "accepted", "done", "bounced", "escalated"]
TaskKind = Literal["RUN", "CLEAR", "CHECK", "SEAT"]
WIRE_STATE: dict[str, str] = {
    "queued": "assigned",
    "sent": "assigned",
    "accepted": "accepted",
    "done": "done",
    "bounced": "bounced",
    "escalated": "bounced",
}
OPEN_STATES: frozenset[str] = frozenset({"queued", "sent", "accepted"})
UNACCEPTED: frozenset[str] = frozenset({"queued", "sent"})


class TaskError(ValueError):
    """An illegal transition or unknown task. Reported, never raised past the API layer."""


@dataclass
class Task:
    id: str
    kind: TaskKind
    table: str
    items: list[dict[str, Any]]
    allergies: list[dict[str, Any]]
    notes: list[str]
    assignee: str
    state: TaskState = "queued"
    priority: float = 0.0
    created_at: str = ""
    assigned_at: float = 0.0
    tried: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def open(self) -> bool:
        return self.state in OPEN_STATES

    def wire(self, state: str | None = None, assignee: str | None = None) -> dict[str, Any]:
        """The Task object as the glasses see it (CONTRACT.md §2)."""
        return {
            "id": self.id,
            "kind": self.kind,
            "table": self.table,
            "items": self.items,
            "allergies": self.allergies,
            "notes": self.notes,
            "state": WIRE_STATE[state or self.state],
            "assignee": assignee or self.assignee,
            "priority": self.priority,
            "createdAt": self.created_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.wire(),
            "backendState": self.state,
            "tried": list(self.tried),
            "history": list(self.history),
        }


@dataclass(frozen=True)
class Outbound:
    """A message the hub must deliver to every socket of `staff` (and to organizers)."""

    staff: str
    message: dict[str, Any]


@dataclass(frozen=True)
class Alert:
    id: str
    level: str
    text: str
    table: str
    since_sec: int = 0
    cleared: bool = False

    def wire(self) -> dict[str, Any]:
        msg: dict[str, Any] = {
            "type": "alert",
            "id": self.id,
            "level": self.level,
            "text": self.text,
            "table": self.table,
            "sinceSec": self.since_sec,
        }
        if self.cleared:
            msg["cleared"] = True
        return msg


class TaskBook:
    def __init__(self, floor: Floor, events: EventLog, escalation_sec: float = 30.0) -> None:
        self.floor = floor
        self.events = events
        self.escalation_sec = escalation_sec
        self.tasks: dict[str, Task] = {}
        self.alerts: dict[str, Alert] = {}

    # ---------- queries ----------

    def get(self, task_id: str) -> Task:
        try:
            return self.tasks[task_id]
        except KeyError:
            raise TaskError(f"unknown task {task_id!r}") from None

    def open_for(self, staff: str) -> list[Task]:
        return [t for t in self.tasks.values() if t.open and t.assignee == staff]

    def open_tasks(self) -> list[Task]:
        return [t for t in self.tasks.values() if t.open]

    # ---------- transitions ----------

    def _move(self, task: Task, to: TaskState, now: float, reason: str) -> None:
        entry = {
            "from": task.state,
            "to": to,
            "assignee": task.assignee,
            "reason": reason,
            "at": now,
        }
        task.history.append(entry)
        task.state = to
        self.events.append("task." + to, taskId=task.id, **entry)

    def create(
        self,
        kind: TaskKind,
        table: str,
        now: float,
        *,
        items: list[dict[str, Any]] | None = None,
        allergies: list[dict[str, Any]] | None = None,
        notes: list[str] | None = None,
        assignee: str | None = None,
        priority: float = 0.0,
        task_id: str | None = None,
    ) -> tuple[Task, list[Outbound]]:
        chain = self.floor.escalation_chain(table)
        who = assignee or chain[0]
        task = Task(
            id=task_id or f"task-{uuid.uuid4().hex[:6]}",
            kind=kind,
            table=table,
            items=items or [],
            allergies=allergies or [],
            notes=notes or [],
            assignee=who,
            priority=priority,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            assigned_at=now,
            tried=[who],
        )
        self.tasks[task.id] = task
        self._move(task, "queued", now, "created")
        return task, [Outbound(who, {"type": "task.assigned", "task": task.wire()})]

    def mark_sent(self, task_id: str, now: float) -> None:
        """The hub delivered the card down a socket."""
        task = self.get(task_id)
        if task.state == "queued":
            self._move(task, "sent", now, "delivered")

    def accept(self, task_id: str, now: float, by: str | None = None) -> list[Outbound]:
        task = self.get(task_id)
        if task.state not in UNACCEPTED:
            raise TaskError(f"{task.id} is {task.state}, cannot accept")
        self._check_owner(task, by)
        self._move(task, "accepted", now, "task.accept")
        return [Outbound(task.assignee, {"type": "task.updated", "task": task.wire()})]

    def done(self, task_id: str, now: float, by: str | None = None) -> list[Outbound]:
        task = self.get(task_id)
        if not task.open:
            raise TaskError(f"{task.id} is {task.state}, cannot finish")
        self._check_owner(task, by)
        self._move(task, "done", now, "task.done")
        out = [Outbound(task.assignee, {"type": "task.updated", "task": task.wire()})]
        return out + self._clear_unacked_alert(task)

    def bounce(self, task_id: str, now: float, by: str | None = None) -> list[Outbound]:
        task = self.get(task_id)
        if task.state not in UNACCEPTED:
            raise TaskError(f"{task.id} is {task.state}, cannot bounce")
        self._check_owner(task, by)
        return self._pass_on(task, now, "bounced", "task.bounce")

    def tick(self, now: float) -> list[Outbound]:
        """Escalate every task nobody accepted within `escalation_sec`."""
        out: list[Outbound] = []
        for task in list(self.tasks.values()):
            if task.state in UNACCEPTED and now - task.assigned_at >= self.escalation_sec:
                out += self._pass_on(task, now, "escalated", "no accept in time")
        return out

    # ---------- internals ----------

    def _check_owner(self, task: Task, by: str | None) -> None:
        if by is not None and by != task.assignee:
            raise TaskError(f"{task.id} belongs to {task.assignee}, not {by}")

    def _next_assignee(self, task: Task) -> str | None:
        for who in self.floor.escalation_chain(task.table):
            if who not in task.tried:
                return who
        return None

    def _pass_on(self, task: Task, now: float, via: TaskState, reason: str) -> list[Outbound]:
        previous = task.assignee
        nxt = self._next_assignee(task)
        if nxt is None:
            return self._raise_unacked_alert(task, now)
        self._move(task, via, now, reason)
        out = [Outbound(previous, {"type": "task.updated", "task": task.wire(state=via)})]
        task.assignee = nxt
        task.assigned_at = now
        task.tried.append(nxt)
        self._move(task, "queued", now, f"after {via} from {previous}")
        out.append(Outbound(nxt, {"type": "task.assigned", "task": task.wire()}))
        return out

    def _raise_unacked_alert(self, task: Task, now: float) -> list[Outbound]:
        alert_id = f"unacked-{task.id}"
        if alert_id in self.alerts:
            return []
        alert = Alert(
            id=alert_id,
            level="urgent",
            text=f"{task.table} {task.kind.lower()} task unacknowledged {{elapsed}}",
            table=task.table,
            since_sec=int(now - task.history[0]["at"]),
        )
        self.alerts[alert_id] = alert
        self.events.append("alert.raised", alertId=alert_id, taskId=task.id)
        return [Outbound(self.floor.manager.id, alert.wire())]

    def _clear_unacked_alert(self, task: Task) -> list[Outbound]:
        alert = self.alerts.pop(f"unacked-{task.id}", None)
        if alert is None:
            return []
        cleared = Alert(alert.id, alert.level, "", alert.table, 0, cleared=True)
        self.events.append("alert.cleared", alertId=alert.id, taskId=task.id)
        return [Outbound(self.floor.manager.id, cleared.wire())]
