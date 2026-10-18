"""Run priority (app/runs.py) against the build-plan rules, plus the FIFO baseline."""

from __future__ import annotations

import pytest

from app.data import Floor, Menu
from app.run_weights import RunWeights
from app.runs import Pass, PassError, Plate, holds, plan_fifo, plan_priority

W = RunWeights()
SECTION = {"T1": "A", "T2": "A", "T3": "A", "T4": "A", "T5": "B", "T6": "B"}


def plate(
    pid: str,
    table: str,
    dish: str,
    course: str,
    temp: str,
    *,
    up: float | None = 0.0,
    ordered: float = 0.0,
) -> Plate:
    order_id, _, line = pid.partition(":")
    return Plate(
        id=pid,
        order_id=order_id,
        line=int(line or 0),
        table=table,
        section=SECTION[table],
        seat=1,
        dish=dish,
        course=course,
        temperature=temp,
        ordered_at=ordered,
        up_at=up,
    )


def ids(runs: list) -> list[list[str]]:
    return [[p.id for p in r.plates] for r in runs]


# ---------- scoring ----------


def test_course_outranks_temperature_appetizers_go_first() -> None:
    cold_app = plate("a:0", "T1", "Scallop Crudo", "appetizer", "cold")
    hot_main = plate("b:0", "T2", "Dry-Aged Ribeye", "main", "hot")
    hot_dessert = plate("c:0", "T5", "Dark Chocolate Torte", "dessert", "hot")  # other section
    runs = plan_priority([hot_dessert, hot_main, cold_app], now=0)
    assert ids(runs) == [["a:0"], ["b:0"], ["c:0"]]
    assert cold_app.score(0) > hot_main.score(0) > hot_dessert.score(0)


def test_within_a_course_hot_beats_cold_and_hot_rises_fastest() -> None:
    hot = plate("a:0", "T1", "Duck Breast", "main", "hot")
    cold = plate("b:0", "T2", "Nicoise Salad", "main", "cold")
    assert hot.score(0) > cold.score(0)
    assert hot.score(120) - hot.score(0) == pytest.approx(2 * W.decay["hot"])
    assert cold.score(120) - cold.score(0) == pytest.approx(2 * W.decay["cold"])


def test_five_minute_ceiling_puts_any_plate_on_top() -> None:
    old_cold_dessert = plate("a:0", "T1", "Lemon Sorbet", "dessert", "cold", up=0)
    fresh_hot_app = plate("b:0", "T2", "Roasted Tomato Soup", "appetizer", "hot", up=301)
    assert ids(plan_priority([fresh_hot_app, old_cold_dessert], now=299)) == [["b:0"], ["a:0"]]
    assert ids(plan_priority([fresh_hot_app, old_cold_dessert], now=301)) == [["a:0"], ["b:0"]]
    assert old_cold_dessert.score(301) > W.ceiling_bonus


# ---------- a table's course leaves together ----------


def test_course_waits_for_its_last_plate_and_names_it() -> None:
    ribeye = plate("o:0", "T1", "Dry-Aged Ribeye", "main", "hot", up=0)
    salad = plate("o:1", "T1", "Nicoise Salad", "main", "cold", up=None)
    assert plan_priority([ribeye, salad], now=240) == []
    assert [h.wire() for h in holds([ribeye, salad])] == [
        {"table": "T1", "course": "main", "waitingOn": ["Nicoise Salad"]}
    ]
    salad.up_at = 250
    runs = plan_priority([ribeye, salad], now=250)
    assert ids(runs) == [["o:0", "o:1"]] and holds([ribeye, salad]) == []


def test_other_courses_of_the_same_table_do_not_hold_a_ready_course() -> None:
    app = plate("o:0", "T1", "Burrata", "appetizer", "cold", up=0)
    main_not_up = plate("o:1", "T1", "Duck Breast", "main", "hot", up=None)
    assert ids(plan_priority([app, main_not_up], now=10)) == [["o:0"]]


def test_bigger_course_gets_a_second_runner() -> None:
    five = [plate(f"o:{i}", "T1", "Cedar Plank Salmon", "main", "hot") for i in range(5)]
    runs = plan_priority(five, now=0)
    assert len(runs) == 1 and runs[0].runners == 2 and len(runs[0].plates) == 5
    assert "2 runners" in runs[0].reason


# ---------- hot pairing ----------


def test_hot_run_pulls_in_hot_plates_from_the_same_section_max_three() -> None:
    hots = [
        plate("a:0", "T1", "Duck Breast", "main", "hot", up=0),
        plate("b:0", "T2", "Duck Breast", "main", "hot", up=1),
        plate("c:0", "T3", "Duck Breast", "main", "hot", up=2),
        plate("d:0", "T4", "Duck Breast", "main", "hot", up=3),
        plate("e:0", "T5", "Duck Breast", "main", "hot", up=0),  # section B
    ]
    runs = plan_priority(hots, now=10)
    assert ids(runs) == [["a:0", "b:0", "c:0"], ["e:0"], ["d:0"]]
    assert runs[0].runners == 1 and runs[0].tables == ["T1", "T2", "T3"]
    assert runs[1].section == "B"


def test_hot_pairing_keeps_the_pulled_in_course_whole() -> None:
    lead = plate("a:0", "T1", "Duck Breast", "main", "hot", up=0)
    pair = [plate(f"b:{i}", "T2", "Duck Breast", "main", "hot", up=1) for i in range(3)]
    runs = plan_priority([lead, *pair], now=10)
    assert ids(runs) == [["a:0"], ["b:0", "b:1", "b:2"]]  # 3 would not fit in 2 spare hands


# ---------- cold never delays hot ----------


def test_hot_run_does_not_wait_for_a_cold_plate_at_another_table() -> None:
    hot = plate("a:0", "T1", "Pan-Roasted Halibut", "main", "hot", up=0)
    cold_not_up = plate("b:0", "T2", "Nicoise Salad", "main", "cold", up=None)
    cold_up = plate("c:0", "T3", "Nicoise Salad", "main", "cold", up=0)
    runs = plan_priority([cold_not_up, cold_up, hot], now=0)
    assert ids(runs) == [["a:0"], ["c:0"]]  # the up cold plate goes on its own, after
    assert not runs[1].hot


def test_cold_plate_joins_a_hot_run_only_for_the_same_table_and_already_up() -> None:
    hot = plate("a:0", "T1", "Pan-Roasted Halibut", "main", "hot", up=0)
    same_table_cold_up = plate("a:1", "T1", "Lemon Sorbet", "dessert", "cold", up=0)
    other_table_cold_up = plate("b:0", "T2", "Lemon Sorbet", "dessert", "cold", up=0)
    runs = plan_priority([other_table_cold_up, same_table_cold_up, hot], now=0)
    assert ids(runs) == [["a:0", "a:1"], ["b:0"]]


def test_mixed_course_of_another_table_is_not_pulled_into_a_hot_run() -> None:
    hot = plate("a:0", "T1", "Duck Breast", "main", "hot", up=0)
    other = [
        plate("b:0", "T2", "Duck Breast", "main", "hot", up=0),
        plate("b:1", "T2", "Nicoise Salad", "main", "cold", up=0),
    ]
    runs = plan_priority([hot, *other], now=0)
    assert ids(runs) == [["a:0"], ["b:0", "b:1"]]


# ---------- FIFO baseline ----------


def test_fifo_runs_plates_in_the_order_they_came_up() -> None:
    plates = [
        plate("a:0", "T1", "Lemon Sorbet", "dessert", "cold", up=5),
        plate("b:0", "T2", "Duck Breast", "main", "hot", up=20),
        plate("c:0", "T3", "Scallop Crudo", "appetizer", "cold", up=30),
        plate("d:0", "T5", "Duck Breast", "main", "hot", up=10),
        plate("e:0", "T6", "Burrata", "appetizer", "cold", up=None),
    ]
    runs = plan_fifo(plates, now=60)
    assert ids(runs) == [["a:0", "d:0", "b:0"], ["c:0"]]
    # priority at the same moment: the hot mains that waited 40-50 s have risen past the
    # 30 s old cold appetizer (12.5); the cold dessert is last whatever its wait
    assert ids(plan_priority(plates, now=60)) == [["d:0"], ["b:0"], ["c:0"], ["a:0"]]
    assert ids(plan_priority(plates, now=30)) == [["c:0"], ["d:0"], ["b:0"], ["a:0"]]


# ---------- the weights are one tunable config ----------


def test_weights_are_tunable_from_a_dict() -> None:
    flat = RunWeights.from_dict({"course_weight": 0, "max_plates_per_runner": 2})
    cold_app = plate("a:0", "T1", "Scallop Crudo", "appetizer", "cold")
    hot_main = plate("b:0", "T2", "Dry-Aged Ribeye", "main", "hot")
    assert ids(plan_priority([cold_app, hot_main], now=0, w=flat)) == [["b:0"], ["a:0"]]
    four = [plate(f"o:{i}", "T1", "Duck Breast", "main", "hot") for i in range(4)]
    assert plan_priority(four, now=0, w=flat)[0].runners == 2
    assert RunWeights.from_dict(W.to_dict()) == W


# ---------- Pass: plates from orders, marking up, dispatch ----------


def test_pass_marks_plates_up_and_dispatches(menu: Menu, floor: Floor) -> None:
    from app.orders import Line

    pass_ = Pass(menu, floor)
    lines = [Line(1, 1, "Dry-Aged Ribeye"), Line(2, 2, "Nicoise Salad")]
    plates = pass_.add_order("o1", "T1", lines, now=0)
    assert [p.id for p in plates] == ["o1:0", "o1:1"] and plates[0].course == "main"
    with pytest.raises(PassError, match="not fired"):
        pass_.mark_up("o9", 0, now=1)
    with pytest.raises(PassError, match="not fired"):
        pass_.mark_up("o1", 2, now=1)
    pass_.mark_up("o1", 0, now=1)
    with pytest.raises(PassError, match="already up"):
        pass_.mark_up("o1", 0, now=2)
    assert pass_.dispatch(now=2) == []
    state = pass_.state(now=2)
    assert state["holds"] == [{"table": "T1", "course": "main", "waitingOn": ["Nicoise Salad"]}]
    assert [p["status"] for p in state["plates"]] == ["up", "waiting"]
    assert state["plates"][0]["line"] == 0 and state["plates"][0]["upSec"] == 1
    pass_.mark_up("o1", 1, now=3)
    runs = pass_.dispatch(now=3)
    assert len(runs) == 1 and runs[0].id == "run-1"
    assert [p["status"] for p in pass_.state(now=3)["plates"]] == ["running", "running"]
    assert pass_.dispatch(now=4) == []  # nothing left to plan
