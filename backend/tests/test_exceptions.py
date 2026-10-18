"""Manager exceptions beyond task alerts: course waits, VIP seated, 86'd dishes."""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.orders import Order
from app.state import Store
from app.tasks import Outbound


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def make(**settings: Any) -> tuple[Store, Clock]:
    clock = Clock()
    return Store.from_settings(Settings(**settings), clock=clock), clock


def fire(store: Store, table: str, dishes: list[tuple[int, str]]) -> Order:
    order_id = ""
    for seat, dish in dishes:
        result, _ = store.orders.dispatch("add_item", {"table": table, "seat": seat, "dish": dish})
        assert "error" not in result, result
        order_id = result["orderId"]
    order = store.orders.fire(order_id)
    store.on_fired(order)
    return order


def alerts(out: list[Outbound]) -> list[dict[str, Any]]:
    return [o.message for o in out if o.message["type"] == "alert"]


# ---------- course wait ----------


def test_course_wait_raises_past_the_threshold_and_clears_when_plates_go_up() -> None:
    store, clock = make()
    store.set_table_status("T4", "seated")
    order = fire(store, "T4", [(1, "halibut"), (2, "ribeye")])
    clock.t = 719
    assert store.course_waits() == []
    clock.t = 840
    out = store.course_waits()
    assert [o.staff for o in out] == ["m1"]
    assert alerts(out) == [
        {
            "type": "alert",
            "id": "course-T4",
            "level": "urgent",
            "text": "T4 waiting {elapsed} on mains",
            "table": "T4",
            "sinceSec": 840,
            "kind": "course_wait",
        }
    ]
    assert store.course_waits() == []  # raised once
    assert store.table_wire("T4")["urgency"] == 3

    store.plate_up(order.id, 0)
    clock.t = 900
    assert store.course_waits() == []  # one plate still not up
    store.plate_up(order.id, 1)
    cleared = alerts(store.course_waits())
    assert [(a["id"], a.get("cleared")) for a in cleared] == [("course-T4", True)]
    assert "course-T4" not in store.book.alerts


def test_course_wait_threshold_comes_from_config() -> None:
    store, clock = make(course_wait_sec=60)
    store.set_table_status("T2", "seated")
    fire(store, "T2", [(1, "soup")])
    clock.t = 61
    assert [a["text"] for a in alerts(store.course_waits())] == ["T2 waiting {elapsed} on apps"]


def test_mains_clock_starts_when_the_table_finished_its_apps() -> None:
    store, clock = make()
    store.set_table_status("T1", "seated")
    order = fire(store, "T1", [(1, "burrata"), (1, "duck")])
    clock.t = 300
    store.plate_up(order.id, 0)  # burrata up, runs out
    store.dispatch()
    assert store.pass_.plates[f"{order.id}:0"].status == "running"
    clock.t = 1500  # 20 min on: still eating the apps, the kitchen holds the duck
    assert store.course_waits() == []
    clock.t = 1800
    store.set_table_status("T1", "waiting")  # apps cleared
    clock.t = 1800 + 719
    assert store.course_waits() == []
    clock.t = 1800 + 721
    [alert] = alerts(store.course_waits())
    assert alert["text"] == "T1 waiting {elapsed} on mains" and alert["sinceSec"] == 721


def test_no_course_wait_once_the_plates_are_up_and_only_need_a_runner() -> None:
    store, clock = make()
    store.set_table_status("T3", "seated")
    order = fire(store, "T3", [(1, "salmon")])
    store.plate_up(order.id, 0)
    clock.t = 2000
    assert store.course_waits() == []  # the pass's own ceiling covers plates up


# ---------- VIP seated ----------


def test_vip_seated_alerts_the_manager_once_and_clears_when_the_table_empties() -> None:
    store, clock = make()
    out = store.set_table_status("T7", "seated", vip=True)
    assert [o.staff for o in out] == ["m1"]
    assert alerts(out) == [
        {
            "type": "alert",
            "id": "vip-T7",
            "level": "info",
            "text": "VIP seated T7",
            "table": "T7",
            "sinceSec": 0,
            "kind": "vip",
        }
    ]
    assert store.set_table_status("T7", "seated", vip=True) == []  # once per party
    assert store.set_table_status("T7", "ordered") == []
    assert store.set_table_status("T7", "seated", vip=True) == []
    cleared = alerts(store.set_table_status("T7", "empty"))
    assert [(a["id"], a.get("cleared")) for a in cleared] == [("vip-T7", True)]
    assert len(alerts(store.set_table_status("T7", "seated", vip=True))) == 1  # the next party


def test_vip_seated_comes_off_the_list_after_vip_alert_sec() -> None:
    store, clock = make(vip_alert_sec=300)
    store.set_table_status("T5", "seated", vip=True)
    clock.t = 200
    store.set_table_status("T5", "ordered")  # the list timer runs from seating, not status
    clock.t = 299
    assert store.exceptions() == []
    clock.t = 300
    assert [a["id"] for a in alerts(store.exceptions())] == ["vip-T5"]
    assert "vip-T5" not in store.book.alerts


def test_non_vip_seating_raises_nothing() -> None:
    store, _ = make()
    assert store.set_table_status("T6", "seated") == []


# ---------- 86 ----------


def test_86_guards_add_item_with_a_question_line_and_un86_lifts_it() -> None:
    store, _ = make()
    halibut = store.menu.find("halibut")
    assert halibut is not None
    alert = store.set_86(halibut, out=True)
    assert alert == {
        "type": "alert",
        "id": "86-halibut",
        "level": "warn",
        "text": "86 halibut",
        "table": "",
        "sinceSec": 0,
        "kind": "86",
    }
    assert store.set_86(halibut, out=True) is None  # already out
    result, order = store.orders.dispatch("add_item", {"table": "T1", "seat": 2, "dish": "halibut"})
    assert "86'd" in result["error"] and result["eightySixed"] == "Pan-Roasted Halibut"
    assert order is not None and order.lines == []
    assert order.draft_wire()["uncertain"] == ["? s2 halibut 86'd"]
    assert store.snapshot()["eightySix"] == ["Pan-Roasted Halibut"]

    cleared = store.set_86(halibut, out=False)
    assert cleared is not None and cleared["cleared"] is True and cleared["id"] == "86-halibut"
    assert "86-halibut" not in store.book.alerts
    result, _ = store.orders.dispatch("add_item", {"table": "T1", "seat": 2, "dish": "halibut"})
    assert result["status"] == "ok"
