"""All in-memory state for one service: menu, floor, tables, orders, tasks, captures, log."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.data import COURSES, TABLE_STATUSES, DataError, Dish, Floor, Menu
from app.events import EventLog
from app.orders import Order, OrderBook
from app.runs import Pass, Plate, Run
from app.tasks import Alert, Outbound, TaskBook

URGENCY_BY_STATUS = {"empty": 0, "seated": 0, "ordered": 0, "waiting": 1, "eating": 0, "check": 1}
WAITING_URGENT_AFTER_SEC = 10 * 60
# how the manager line names the course a table is waiting on ("T4 waiting 14m on mains")
COURSE_WORD = {"appetizer": "apps", "main": "mains", "dessert": "dessert"}


@dataclass
class TableLive:
    status: str = "empty"
    since: float = 0.0
    vip: bool = False  # this party was seated as VIP (POST /tables/{id}/status); off when empty
    vip_at: float = 0.0


@dataclass
class Capture:
    id: str
    staff: str
    table: str | None
    started: float
    frames: int = 0
    bytes: int = 0
    open: bool = True


@dataclass
class Store:
    settings: Settings
    menu: Menu
    floor: Floor
    events: EventLog = field(default_factory=EventLog)
    tables: dict[str, TableLive] = field(init=False)
    book: TaskBook = field(init=False)
    orders: OrderBook = field(init=False)
    captures: dict[str, Capture] = field(default_factory=dict)
    pass_: Pass = field(init=False)
    # seconds, monotonic; the dinner-rush simulator passes a simulated clock (sim/)
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)

    def __post_init__(self) -> None:
        self.reset()

    @classmethod
    def from_settings(
        cls, settings: Settings, clock: Callable[[], float] = time.monotonic
    ) -> Store:
        return cls(
            settings,
            Menu.load(settings.data_dir / "menu.json"),
            Floor.load(settings.data_dir / "floor.json"),
            clock=clock,
        )

    def now(self) -> float:
        return self.clock()

    def reset(self) -> None:
        now = self.now()
        self.tables = {t: TableLive("empty", now) for t in self.floor.tables}
        self.book = TaskBook(
            self.floor,
            self.events,
            self.settings.escalation_sec,
            self.settings.offline_escalation_sec,
            self.settings.done_sec,
        )
        self.orders = OrderBook(self.menu, set(self.floor.tables))
        self.captures = {}
        self.pass_ = Pass(self.menu, self.floor)
        self.served_at: dict[str, float] = {}  # table -> when its last plates left the pass
        self.events.append("service.reset")

    # ---------- tables ----------

    def set_table_status(self, table: str, status: str, vip: bool = False) -> list[Outbound]:
        """Returns the manager's "VIP seated" alert (raised once per party) or its clear."""
        if status not in TABLE_STATUSES:
            raise DataError(f"status must be one of {TABLE_STATUSES}")
        table = self.floor.table(table).id
        live = self.tables[table]
        if live.status != status:
            live.status, live.since = status, self.now()
            self.events.append("table.status", table=table, status=status)
        if status == "empty" and live.vip:
            live.vip = False
            return self._clear_alert(f"vip-{table}")
        if status == "seated" and vip and not live.vip:
            live.vip, live.vip_at = True, self.now()
            return self._raise_alert(
                Alert(f"vip-{table}", "info", f"VIP seated {table}", table, kind="vip")
            )
        return []

    def _raise_alert(self, alert: Alert, to: list[str] | None = None) -> list[Outbound]:
        self.book.alerts[alert.id] = alert
        self.events.append("alert.raised", alertId=alert.id, table=alert.table)
        return [Outbound(s, alert.wire()) for s in to or [self.floor.manager.id]]

    def _clear_alert(self, alert_id: str, to: list[str] | None = None) -> list[Outbound]:
        alert = self.book.alerts.pop(alert_id, None)
        if alert is None:
            return []
        self.events.append("alert.cleared", alertId=alert_id, table=alert.table)
        return [Outbound(s, alert.clear().wire()) for s in to or [self.floor.manager.id]]

    def exceptions(self) -> list[Outbound]:
        """The ticker's checks: course waits, and "VIP seated" off the list after vip_alert_sec."""
        out = self.course_waits()
        now = self.now()
        for table, live in self.tables.items():
            alert = self.book.alerts.get(f"vip-{table}")
            if alert and now - live.vip_at >= self.settings.vip_alert_sec:
                out += self._clear_alert(alert.id)
        return out

    def table_wire(self, table_id: str) -> dict[str, Any]:
        t, live = self.floor.table(table_id), self.tables[table_id]
        since = int(self.now() - live.since)
        urgency = URGENCY_BY_STATUS[live.status]
        if live.status == "waiting" and since >= WAITING_URGENT_AFTER_SEC:
            urgency = 3
        if f"course-{t.id}" in self.book.alerts:
            urgency = 3
        return {
            "table": t.id,
            "status": live.status,
            "sinceSec": since,
            "x": t.x,
            "y": t.y,
            "urgency": urgency,
        }

    def floor_state(self) -> dict[str, Any]:
        return {"type": "floor.state", "tables": [self.table_wire(t) for t in self.floor.tables]}

    # ---------- orders -> the pass -> run tasks ----------

    def on_fired(self, order: Order) -> None:
        """A confirmed order: the table is 'ordered' and its lines become plates at the pass."""
        self.set_table_status(order.table, "ordered")
        plates = self.pass_.add_order(order.id, order.table, order.lines, self.now())
        self.events.append(
            "pass.ticket", orderId=order.id, table=order.table, plates=[p.id for p in plates]
        )

    def plate_up(self, order_id: str, line: int) -> Plate:
        """Mark a plate up at the pass. Call `dispatch()` afterwards to hand out runs."""
        plate = self.pass_.mark_up(order_id, line, self.now())
        self.events.append("pass.up", plateId=plate.id, table=plate.table, dish=plate.dish)
        return plate

    def free_runners(self) -> dict[str, str]:
        """Servers with free hands, mapped to the section they run by default.

        Busy means an open RUN (holding or about to hold plates) or any other task they have
        accepted (taking an order, running a check): a RUN card would only sit and escalate.
        """
        free: dict[str, str] = {}
        for server in self.floor.servers.values():
            if self.hands_full(server.id):
                continue
            home = [sec for sec, srv in self.floor.sections.items() if srv == server.id]
            free[server.id] = home[0] if home else (server.sections[0] if server.sections else "")
        return free

    def hands_full(self, staff: str) -> bool:
        return any(t.kind == "RUN" or t.state == "accepted" for t in self.book.open_for(staff))

    def dispatch(self) -> list[Outbound]:
        """Re-plan the pass: the best run goes to the next free server, the rest keep waiting.

        Called after food up, after every task state change and on the ticker (so the
        5-minute ceiling fires without anyone pressing a button). The manager only runs food
        past the ceiling. Servers held for a run get no new floor tasks (`TaskBook.held`).
        """
        now = self.now()
        manager = self.floor.manager.id
        extra = {} if self.hands_full(manager) else {manager: ""}
        out: list[Outbound] = []
        for run in self.pass_.dispatch(now, self.free_runners(), extra):
            out += self._run_tasks(run, now)
        self.book.held = frozenset(self.pass_.reserved)
        return out

    def _run_tasks(self, run: Run, now: float) -> list[Outbound]:
        for p in run.plates:
            self.served_at[p.table] = now
        per_runner = self.pass_.weights.max_plates_per_runner
        out: list[Outbound] = []
        for i in range(run.runners):
            plates = run.plates[i * per_runner : (i + 1) * per_runner]
            notes = [run.reason] if i == 0 else [f"runner {i + 1} of {run.runners}: {run.reason}"]
            if len(run.tables) > 1:
                notes.append("also " + ", ".join(t for t in run.tables if t != run.table))
            task, outbound = self.book.create(
                "RUN",
                run.table,
                now,
                items=[
                    {
                        "qty": 1,
                        "dish": f"{p.dish} ({p.table})" if p.table != run.table else p.dish,
                        "seats": [p.seat],
                    }
                    for p in plates
                ],
                notes=notes,
                assignee=run.assignees[i],
                priority=run.score,
            )
            self.events.append(
                "pass.run",
                runId=run.id,
                taskId=task.id,
                assignee=task.assignee,
                plates=[p.id for p in plates],
            )
            out += outbound
        return out

    # ---------- 86 ----------

    @property
    def eighty_six(self) -> list[str]:
        return sorted(self.orders.out)

    def set_86(self, dish: Dish, out: bool) -> dict[str, Any] | None:
        """86 a dish (or bring it back). Returns the alert for every server and the manager,
        or None if nothing changed. Open 86 alerts replay to anyone who connects (hub)."""
        alert_id = f"86-{dish.short.replace(' ', '-')}"
        if out == (dish.name in self.orders.out):
            return None
        if out:
            self.orders.out.add(dish.name)
            alert = Alert(alert_id, "warn", f"86 {dish.short}", "", kind="86")
            self.book.alerts[alert_id] = alert
            self.events.append("menu.86", dish=dish.name, alertId=alert_id)
            return alert.wire()
        self.orders.out.discard(dish.name)
        cleared = self.book.alerts.pop(alert_id).clear()
        self.events.append("menu.un86", dish=dish.name, alertId=alert_id)
        return cleared.wire()

    # ---------- course waits ----------

    def _eaten_at(self, table: str) -> float | None:
        """When the table last finished a course: a CLEAR done there, or status set to waiting."""
        marks = [
            t.done_at
            for t in self.book.tasks.values()
            if t.kind == "CLEAR" and t.table == table and t.done_at is not None
        ]
        live = self.tables[table]
        if live.status == "waiting":
            marks.append(live.since)
        return max(marks, default=None)

    def course_wait(self, table: str) -> tuple[str, float] | None:
        """(course, waiting since) if the table is waiting on its next course to reach the pass.

        The next course is the first one with a plate not up yet. The clock starts when that
        course was fired or, if an earlier course went out before it was fired, when the table
        finished eating (`_eaten_at`). Still eating, or plates up and only waiting for a runner
        (the pass's own job): no wait.
        """
        plates = [p for p in self.pass_.plates.values() if p.table == table]
        for i, course in enumerate(COURSES):
            waiting = [p for p in plates if p.course == course and p.up_at is None]
            if not waiting:
                continue
            earlier = [p for p in plates if p.course in COURSES[:i]]
            if any(p.run_id is None for p in earlier):
                return None
            start = min(p.ordered_at for p in waiting)
            served = self.served_at.get(table)
            if earlier and served is not None and served >= start:
                eaten = self._eaten_at(table)
                if eaten is None or eaten < served:
                    return None
                start = eaten
            return course, start
        return None

    def course_waits(self) -> list[Outbound]:
        """Raise "T4 waiting 14m on mains" past `course_wait_sec`; clear when the plates go up."""
        now = self.now()
        out: list[Outbound] = []
        want: dict[str, Alert] = {}
        for table in self.floor.tables:
            if self.tables[table].status == "empty":
                continue
            wait = self.course_wait(table)
            if wait is None or now - wait[1] < self.settings.course_wait_sec:
                continue
            course, start = wait
            alert = Alert(
                id=f"course-{table}",
                level="urgent",
                text=f"{table} waiting {{elapsed}} on {COURSE_WORD[course]}",
                table=table,
                since_sec=int(now - start),
                kind="course_wait",
            )
            want[alert.id] = alert
        for alert_id, alert in list(self.book.alerts.items()):
            if alert.kind != "course_wait":
                continue
            if alert_id in want and want[alert_id].text == alert.text:
                del want[alert_id]
                continue
            out += self._clear_alert(alert_id)
        for alert in want.values():
            out += self._raise_alert(alert)
        return out

    # ---------- captures ----------

    def start_capture(
        self, capture_id: str, staff: str, table: str | None, *, bind: bool = True
    ) -> Capture:
        """The capture's table: the one the glasses sent, else the server's open ORDER task
        (accepted first), else none: the server says it in the clip. A command stream
        (bind=False) has no table."""
        if table is None and bind:
            orders = [t for t in self.book.open_for(staff) if t.kind == "ORDER"]
            orders.sort(key=lambda t: t.state != "accepted")
            table = orders[0].table if orders else None
        cap = Capture(capture_id, staff, table, self.now())
        self.captures[capture_id] = cap
        self.events.append("capture.start", captureId=capture_id, staff=staff, table=table)
        return cap

    def stop_capture(self, capture_id: str) -> Capture | None:
        cap = self.captures.get(capture_id)
        if cap and cap.open:
            cap.open = False
            self.events.append(
                "capture.stop", captureId=capture_id, frames=cap.frames, bytes=cap.bytes
            )
        return cap

    def capture_owner(self, table: str) -> str | None:
        """Who sees order.draft for this table: the open capture's server, else the section's."""
        for cap in reversed(list(self.captures.values())):
            if cap.table == table and cap.open:
                return cap.staff
        return self.floor.escalation_chain(table)[0]

    # ---------- snapshot ----------

    def snapshot(self) -> dict[str, Any]:
        return {
            "tables": [self.table_wire(t) for t in self.floor.tables],
            "tasks": [t.to_dict() for t in self.book.tasks.values()],
            "orders": [o.to_dict() for o in self.orders.orders.values()],
            "alerts": [a.wire() for a in self.book.alerts.values()],
            "eightySix": self.eighty_six,
            "captures": [c.__dict__ for c in self.captures.values()],
            "pass": self.pass_.state(self.now()),
            "events": len(self.events),
        }
