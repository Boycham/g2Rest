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
from app.telemetry import Trace, current_trace

TaskState = Literal["queued", "sent", "accepted", "done", "bounced", "escalated"]
TaskKind = Literal["RUN", "CLEAR", "CHECK", "SEAT", "ORDER"]
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
    sent_at: float | None = None
    accepted_at: float | None = None  # starts the done timer (CONTRACT.md §6)
    done_at: float | None = None
    tried: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    trace: Trace | None = None  # the Sentry trace it was created in: accept and done continue it

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
    def __init__(
        self,
        floor: Floor,
        events: EventLog,
        escalation_sec: float = 30.0,
        offline_escalation_sec: float = 120.0,
        done_sec: float = 300.0,
    ) -> None:
        self.floor = floor
        self.events = events
        self.escalation_sec = escalation_sec
        self.offline_escalation_sec = offline_escalation_sec
        self.done_sec = done_sec
        self.tasks: dict[str, Task] = {}
        self.alerts: dict[str, Alert] = {}
        # servers the pass holds for a run (`Pass.reserved`): no new floor tasks go to them
        self.held: frozenset[str] = frozenset()
        # staff -> (task id, action, state before it): one level of undo for task.revert
        self.last_action: dict[str, tuple[str, str, TaskState]] = {}

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

    def _move(self, task: Task, to: TaskState, now: float, reason: str, **timing: float) -> None:
        """`timing` (acceptSec, ticketSec) goes to the event log only: the Tiger Data
        aggregates (app/schema.sql) read it, the task history stays as it was."""
        entry = {
            "from": task.state,
            "to": to,
            "assignee": task.assignee,
            "reason": reason,
            "at": now,
        }
        task.history.append(entry)
        task.state = to
        self.events.append("task." + to, taskId=task.id, kind=task.kind, **entry, **timing)

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
            trace=current_trace(),
        )
        self.tasks[task.id] = task
        self._move(task, "queued", now, "created")
        return task, [Outbound(who, {"type": "task.assigned", "task": task.wire()})]

    def mark_sent(self, task_id: str, now: float) -> None:
        """The hub delivered the card down a socket."""
        task = self.get(task_id)
        if task.state == "queued":
            task.sent_at = now
            self._move(task, "sent", now, "delivered")

    def accept(self, task_id: str, now: float, by: str | None = None) -> list[Outbound]:
        task = self.get(task_id)
        if task.state not in UNACCEPTED:
            raise TaskError(f"{task.id} is {task.state}, cannot accept")
        self._check_owner(task, by)
        self.last_action[task.assignee] = (task.id, "accept", task.state)
        task.accepted_at = now
        timing = {"acceptSec": round(now - task.sent_at, 3)} if task.sent_at is not None else {}
        self._move(task, "accepted", now, "task.accept", **timing)
        return [Outbound(task.assignee, {"type": "task.updated", "task": task.wire()})]

    def done(self, task_id: str, now: float, by: str | None = None) -> list[Outbound]:
        task = self.get(task_id)
        if not task.open:
            raise TaskError(f"{task.id} is {task.state}, cannot finish")
        self._check_owner(task, by)
        self.last_action[task.assignee] = (task.id, "done", task.state)
        task.done_at = now
        start = task.accepted_at if task.accepted_at is not None else task.assigned_at
        self._move(task, "done", now, "task.done", ticketSec=round(now - start, 3))
        out = [Outbound(task.assignee, {"type": "task.updated", "task": task.wire()})]
        return out + self._clear_unacked_alert(task)

    def bounce(self, task_id: str, now: float, by: str | None = None) -> list[Outbound]:
        task = self.get(task_id)
        if task.state not in UNACCEPTED:
            raise TaskError(f"{task.id} is {task.state}, cannot bounce")
        self._check_owner(task, by)
        return self._hand(task, now, "bounce", None)

    def handoff(self, task_id: str, now: float, by: str | None, to: str) -> list[Outbound]:
        """Give an open task (accepted or not) to `to`, a staff id or name."""
        task = self.get(task_id)
        if not task.open:
            raise TaskError(f"{task.id} is {task.state}, cannot hand off")
        self._check_owner(task, by)
        target = self.staff_id(to)
        if target == task.assignee:
            raise TaskError("it's already yours")
        return self._hand(task, now, "handoff", target)

    def revert(self, now: float, by: str, task_id: str | None = None) -> list[Outbound]:
        """Undo `by`'s last accept, done, bounce or handoff, if nobody has moved it on since."""
        last = self.last_action.get(by)
        if last is None or (task_id is not None and task_id != last[0]):
            raise TaskError("nothing to revert")
        tid, action, before = last
        task = self.get(tid)
        if action in ("accept", "done"):
            if task.assignee != by or task.state != ("accepted" if action == "accept" else "done"):
                raise TaskError(f"can't undo {action}, the task moved on")
            to: TaskState = "sent" if action == "accept" else before
            self._move(task, to, now, f"revert {action}")
            task.done_at = None
            if to == "sent":
                task.sent_at, task.accepted_at = now, None  # a fresh escalation timer
            del self.last_action[by]
            kind = "task.updated" if action == "accept" else "task.assigned"  # done: card returns
            return [Outbound(by, {"type": kind, "task": task.wire()})]
        holder = task.assignee
        if task.state not in UNACCEPTED:
            done = "accepted" if task.state == "accepted" else "finished"
            raise TaskError(f"{self.name(holder)} already {done} it")
        self._move(task, "bounced", now, f"revert {action} by {by}")
        out = [Outbound(holder, {"type": "task.updated", "task": task.wire(state="bounced")})]
        if task.tried and task.tried[-1] == holder:
            task.tried.pop()
        task.assignee, task.assigned_at, task.sent_at = by, now, None
        task.accepted_at = now if before == "accepted" else None
        self._move(task, "accepted" if before == "accepted" else "queued", now, f"back to {by}")
        del self.last_action[by]
        return [*out, Outbound(by, {"type": "task.assigned", "task": task.wire()})]

    # ---------- timing ----------

    def overdue(self, now: float) -> list[Task]:
        """Accepted tasks not done within `done_sec` that nobody has flagged yet."""
        return [
            t
            for t in self.tasks.values()
            if t.state == "accepted"
            and t.accepted_at is not None
            and now - t.accepted_at >= self.done_sec
            and f"slow-{t.id}" not in self.alerts
        ]

    def reroute(self, task_id: str, now: float, to: str | None) -> list[Outbound]:
        """A task held too long: tell the manager, and give it to `to` unless it's a RUN.

        A RUN's plates are already in the server's hands, so it only raises the alert.
        Re-checks the task, because the router call before this one awaits.
        """
        task = self.get(task_id)
        if task not in self.overdue(now):
            return []
        held, holder = now - (task.accepted_at or now), task.assignee
        moved = task.kind != "RUN" and to not in (None, holder)
        tail = f", moved to {self.name(to)}" if moved and to else ""
        alert = Alert(
            id=f"slow-{task.id}",
            level="warn",
            text=f"{task.table} {task.kind.lower()}: {self.name(holder)} {clock(held)}{tail}",
            table=task.table,
            since_sec=int(held),
        )
        self.alerts[alert.id] = alert
        self.events.append("alert.raised", alertId=alert.id, taskId=task.id)
        out = [Outbound(self.floor.manager.id, alert.wire())]
        if moved and to:
            out += self._pass_on(task, now, "escalated", f"not done after {clock(held)}", to)
        return out

    def stats(self, now: float) -> list[dict[str, Any]]:
        """Per server: tasks done, average accept-to-done time (all, per kind), open tasks."""
        rows = []
        for s in self.floor.servers.values():
            secs: dict[str, list[float]] = {}
            for t in self.tasks.values():
                if t.state == "done" and t.assignee == s.id and t.done_at is not None:
                    start = t.accepted_at if t.accepted_at is not None else t.assigned_at
                    secs.setdefault(t.kind, []).append(t.done_at - start)
            flat = [x for xs in secs.values() for x in xs]
            rows.append(
                {
                    "id": s.id,
                    "name": s.name,
                    "done": len(flat),
                    "avgSec": round(sum(flat) / len(flat)) if flat else None,
                    "avgSecByKind": {k: round(sum(v) / len(v)) for k, v in secs.items()},
                    "open": [
                        {
                            "taskId": t.id,
                            "kind": t.kind,
                            "table": t.table,
                            "state": t.wire()["state"],
                            "heldSec": round(now - (t.accepted_at or t.assigned_at)),
                        }
                        for t in self.open_for(s.id)
                    ],
                }
            )
        return rows

    def staff_id(self, who: str) -> str:
        for s in [*self.floor.servers.values(), self.floor.manager]:
            if who.strip().lower() in (s.id.lower(), s.name.lower()):
                return s.id
        raise TaskError(f"no one called {who}")

    def name(self, staff: str) -> str:
        s = self.floor.servers.get(staff)
        return s.name if s else self.floor.manager.name if staff == self.floor.manager.id else staff

    def tick(self, now: float) -> list[Outbound]:
        """Escalate every task nobody accepted in time.

        `sent` (the card went down a socket): `escalation_sec` after it was sent. `queued` (the
        assignee's socket is offline, so it was never sent): `offline_escalation_sec` after it
        was assigned (CONTRACT.md §8). The timer stops at `accepted`.
        """
        out: list[Outbound] = []
        for task in list(self.tasks.values()):
            if task.state == "sent" and task.sent_at is not None:
                if now - task.sent_at >= self.escalation_sec:
                    out += self._pass_on(task, now, "escalated", "no accept in time")
            elif task.state == "queued" and now - task.assigned_at >= self.offline_escalation_sec:
                out += self._pass_on(task, now, "escalated", "assignee offline")
        return out

    # ---------- internals ----------

    def _check_owner(self, task: Task, by: str | None) -> None:
        if by is not None and by != task.assignee:
            raise TaskError(f"{task.id} belongs to {task.assignee}, not {by}")

    def _next_assignee(self, task: Task) -> str | None:
        for who in self.floor.escalation_chain(task.table):
            if who not in task.tried and (task.kind == "RUN" or who not in self.held):
                return who
        return None

    def _hand(self, task: Task, now: float, action: str, to: str | None) -> list[Outbound]:
        """Bounce or hand off, remembering it for task.revert if the task really moved."""
        previous, before = task.assignee, task.state
        reason = f"task.handoff to {to}" if to else "task.bounce"
        out = self._pass_on(task, now, "bounced", reason, to)
        if task.assignee != previous:
            self.last_action[previous] = (task.id, action, before)
        return out

    def _pass_on(
        self, task: Task, now: float, via: TaskState, reason: str, nxt: str | None = None
    ) -> list[Outbound]:
        previous = task.assignee
        nxt = nxt or self._next_assignee(task)
        if nxt is None:
            return self._raise_unacked_alert(task, now)
        self._move(task, via, now, reason)
        out = [Outbound(previous, {"type": "task.updated", "task": task.wire(state=via)})]
        task.assignee = nxt
        task.assigned_at = now
        task.sent_at = task.accepted_at = None
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
        """Done clears the task's alerts: unacknowledged, and held too long."""
        out = []
        for alert_id in (f"unacked-{task.id}", f"slow-{task.id}"):
            alert = self.alerts.pop(alert_id, None)
            if alert is None:
                continue
            cleared = Alert(alert.id, alert.level, "", alert.table, 0, cleared=True)
            self.events.append("alert.cleared", alertId=alert.id, taskId=task.id)
            out.append(Outbound(self.floor.manager.id, cleared.wire()))
        return out


def clock(sec: float) -> str:
    return f"{int(sec) // 60}:{int(sec) % 60:02d}"
