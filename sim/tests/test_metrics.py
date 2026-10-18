"""metrics.compute on a tiny hand-made event stream, every number worked out by hand."""

from __future__ import annotations

from metrics import compute, percentile

DISHES = {
    "Steak": {"course": "main", "temperature": "hot"},
    "Salad": {"course": "appetizer", "temperature": "cold"},
}


def ev(t: float, type: str, **data: object) -> dict[str, object]:
    return {"t": t, "type": type, "data": data}


def up(t: float, plate: str, table: str, dish: str) -> dict[str, object]:
    return ev(t, "pass.up", plateId=plate, table=table, dish=dish)


EVENTS = [
    up(0, "o1:0", "T1", "Steak"),
    up(10, "o1:1", "T1", "Steak"),
    up(20, "o2:0", "T2", "Salad"),
    ev(30, "pass.run", runId="run-1", taskId="task-a", plates=["o1:0", "o1:1", "o2:0"]),
    ev(40, "sim.reserved", idle=["s2"], busy=[]),
    ev(50, "sim.task", taskId="task-x", kind="ORDER"),
    ev(60, "task.escalated", taskId="task-x", assignee="s1"),
    ev(70, "sim.reserved", idle=["s1", "s2"], busy=["s1"]),
    ev(100, "task.done", taskId="task-a", assignee="s1"),
    up(100, "o3:0", "T1", "Steak"),
    ev(100, "sim.reserved", idle=[], busy=[]),
    ev(430, "pass.run", runId="run-2", taskId="task-b", plates=["o3:0"]),
    ev(440, "task.escalated", taskId="task-b", assignee="s2"),
    ev(490, "task.done", taskId="task-b", assignee="m1"),
]


def test_percentile_is_nearest_rank() -> None:
    xs = [float(x) for x in range(1, 11)]
    assert percentile(xs, 50) == 5
    assert percentile(xs, 90) == 9
    assert percentile(xs, 100) == 10
    assert percentile([], 50) is None


def test_pass_wait_split_by_temperature() -> None:
    m = compute(EVENTS, DISHES, ["s1", "s2"])
    assert m["plates"] == 4
    assert m["waitSec"]["hot"] == {"n": 3, "median": 30.0, "p90": 330.0, "max": 330.0}
    assert m["waitSec"]["cold"] == {"n": 1, "median": 10.0, "p90": 10.0, "max": 10.0}
    assert m["waitSec"]["warm"]["n"] == 0 and m["waitSec"]["warm"]["median"] is None
    assert m["stillAtPass"]["total"] == 0


def test_ceiling_pairing_and_runs() -> None:
    m = compute(EVENTS, DISHES, ["s1", "s2"])
    assert m["ceilingPlates"] == {"hot": 1, "warm": 0, "room": 0, "cold": 0, "total": 1}
    assert m["runs"] == 2 and m["runTasks"] == 2
    assert m["multiTableRuns"] == 1  # run-1 carries T1 and T2
    assert m["escalatedRunTasks"] == 1
    assert m["runTasksDoneBy"] == {"m1": 1, "s1": 1}
    assert m["floorTasks"] == {"ORDER": 1} and m["escalatedFloorTasks"] == 1
    assert m["courses"]["leftTogether"] == 3 and m["courses"]["n"] == 3


def test_idle_while_reserved_total_per_server_and_empty_handed() -> None:
    m = compute(EVENTS, DISHES, ["s1", "s2"])
    idle = m["idleReservedSec"]
    assert idle["perServer"] == {"s1": 30, "s2": 60}
    assert idle["total"] == 90
    assert idle["emptyHanded"] == 60  # s1 was holding an accepted task for its 30 s
    assert idle["emptyHandedPerServer"] == {"s1": 0, "s2": 60}
    assert idle["spans"] == 2


def test_plate_to_table_and_course_at_table() -> None:
    m = compute(EVENTS, DISHES, ["s1", "s2"])
    assert m["toTableSec"]["hot"] == {"n": 3, "median": 100.0, "p90": 390.0, "max": 390.0}
    assert m["toTableSec"]["cold"]["median"] == 80.0
    # o1 mains: both up by t=10, left at 30 -> 20 s each; o3: 330 s
    assert m["hotWaitAfterCourseUpSec"] == {"n": 3, "median": 20.0, "p90": 330.0, "max": 330.0}
    # o1 mains: last up 10, at the table 100 -> 90; o3: 100 -> 490 = 390
    assert m["hotCourseToTableSec"] == {"n": 2, "median": 90.0, "p90": 390.0, "max": 390.0}


def test_open_reservation_closes_at_the_last_event() -> None:
    events = [up(0, "o1:0", "T1", "Steak"), ev(5, "sim.reserved", idle=["s1"], busy=[])]
    events.append(ev(65, "pass.run", runId="run-1", taskId="t", plates=["o1:0"]))
    m = compute(events, DISHES, ["s1", "s2"])
    assert m["idleReservedSec"]["perServer"] == {"s1": 60, "s2": 0}


def test_hot_course_hold_floor() -> None:
    # o1's two steaks came up 10 s apart: the first must wait 10 s for its course, whatever runs it
    m = compute(EVENTS, DISHES, ["s1", "s2"])
    assert m["hotCourseHoldSec"] == {"n": 3, "median": 0.0, "p90": 10.0, "max": 10.0}
