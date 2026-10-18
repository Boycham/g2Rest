"""All in-memory state for one service: menu, floor, tables, orders, tasks, captures, log."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.data import TABLE_STATUSES, DataError, Floor, Menu
from app.events import EventLog
from app.orders import Order, OrderBook
from app.runs import Pass, Run
from app.tasks import Outbound, TaskBook

URGENCY_BY_STATUS = {"empty": 0, "seated": 0, "ordered": 0, "waiting": 1, "eating": 0, "check": 1}
WAITING_URGENT_AFTER_SEC = 10 * 60


@dataclass
class TableLive:
    status: str = "empty"
    since: float = 0.0


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

    def __post_init__(self) -> None:
        self.reset()

    @classmethod
    def from_settings(cls, settings: Settings) -> Store:
        return cls(
            settings,
            Menu.load(settings.data_dir / "menu.json"),
            Floor.load(settings.data_dir / "floor.json"),
        )

    @staticmethod
    def now() -> float:
        return time.monotonic()

    def reset(self) -> None:
        now = self.now()
        self.tables = {t: TableLive("empty", now) for t in self.floor.tables}
        self.book = TaskBook(self.floor, self.events, self.settings.escalation_sec)
        self.orders = OrderBook(self.menu, set(self.floor.tables))
        self.captures = {}
        self.pass_ = Pass(self.menu, self.floor)
        self.events.append("service.reset")

    # ---------- tables ----------

    def set_table_status(self, table: str, status: str) -> None:
        if status not in TABLE_STATUSES:
            raise DataError(f"status must be one of {TABLE_STATUSES}")
        live = self.tables[self.floor.table(table).id]
        if live.status != status:
            live.status, live.since = status, self.now()
            self.events.append("table.status", table=table, status=status)

    def table_wire(self, table_id: str) -> dict[str, Any]:
        t, live = self.floor.table(table_id), self.tables[table_id]
        since = int(self.now() - live.since)
        urgency = URGENCY_BY_STATUS[live.status]
        if live.status == "waiting" and since >= WAITING_URGENT_AFTER_SEC:
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

    def plate_up(self, order_id: str, line: int) -> list[Outbound]:
        """Mark a plate up, re-plan the pass and create one RUN task per runner of each run."""
        now = self.now()
        plate = self.pass_.mark_up(order_id, line, now)
        self.events.append("pass.up", plateId=plate.id, table=plate.table, dish=plate.dish)
        out: list[Outbound] = []
        for run in self.pass_.dispatch(now):
            out += self._run_tasks(run, now)
        return out

    def _run_tasks(self, run: Run, now: float) -> list[Outbound]:
        chain = self.floor.escalation_chain(run.table)
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
                assignee=chain[min(i, len(chain) - 1)],
                priority=run.score,
            )
            self.events.append(
                "pass.run", runId=run.id, taskId=task.id, plates=[p.id for p in plates]
            )
            out += outbound
        return out

    # ---------- captures ----------

    def start_capture(self, capture_id: str, staff: str, table: str | None) -> Capture:
        if table is None:
            current = self.book.open_for(staff)
            table = current[0].table if current else None
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
            "captures": [c.__dict__ for c in self.captures.values()],
            "pass": self.pass_.state(self.now()),
            "events": len(self.events),
        }
