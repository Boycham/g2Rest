"""Store.now() reads an injectable clock, so the dinner-rush simulator can run without sleeping."""

from __future__ import annotations

import time

from app.config import Settings
from app.orders import Line, Order
from app.state import Store


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_default_clock_is_monotonic() -> None:
    store = Store.from_settings(Settings())
    before = time.monotonic()
    assert before <= store.now() <= time.monotonic()


def test_injected_clock_drives_tables_tasks_and_the_pass() -> None:
    clock = FakeClock(1000.0)
    store = Store.from_settings(Settings(), clock=clock)
    assert store.now() == 1000.0

    clock.t = 1060.0
    store.set_table_status("T1", "waiting")
    clock.t = 1060.0 + 11 * 60
    assert store.table_wire("T1")["sinceSec"] == 11 * 60
    assert store.table_wire("T1")["urgency"] == 3  # waiting > 10 min, on simulated time

    order = Order("order-x", "T1", lines=[Line(1, 1, "Pan-Roasted Halibut")], status="fired")
    store.on_fired(order)
    clock.t += 30
    store.plate_up("order-x", 0)
    clock.t += 90
    (run,) = [t for t in store.dispatch() if t.message["type"] == "task.assigned"]
    task = store.book.get(run.message["task"]["id"])
    assert task.assigned_at == clock.t
    assert store.pass_.state(store.now())["plates"][0]["upSec"] == 90
