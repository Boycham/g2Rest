"""Pass metrics from a time-stamped event stream, the same for the offline and the live run.

An event is `{"t": seconds since service start, "type": ..., "data": {...}}`: the backend's own
event log (`pass.up`, `pass.run`, `task.*`) stamped with the simulated clock, plus the
simulator's `sim.reserved {idle: [server], busy: [server], runners, plates}` records, written
whenever the set of servers held for a bigger run changes (`idle: []` when it ends). `idle` is
every server the pass counts as free (`Store.free_runners`) while the best ready run can't go;
`busy` is the subset whose hands were full with accepted floor work at the time.

Hot-plate wait is `pass.up` to `pass.run` for each plate, split by the dish's temperature: the
time the plate waits for the pass to hand it to someone. `toTableSec` is `pass.up` to the
`task.done` of the RUN that carried it, which adds the server's reaction and the walk.
Two numbers separate the planners' trade-off: `hotWaitAfterCourseUpSec` counts a hot plate's
wait only from the moment the last plate of its course came up (the part the "whole course goes
out together" hold doesn't explain), and `hotCourseToTableSec` is, per course with a hot plate,
last plate up to the last plate's RUN done: how long after the kitchen finished the course the
whole table had it.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

TEMPERATURES = ("hot", "warm", "room", "cold")


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..100); None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def summary(values: list[float]) -> dict[str, Any]:
    def r(x: float | None) -> float | None:
        return None if x is None else round(x, 1)

    return {
        "n": len(values),
        "median": r(percentile(values, 50)),
        "p90": r(percentile(values, 90)),
        "max": r(max(values) if values else None),
    }


def compute(
    events: list[dict[str, Any]],
    dishes: dict[str, dict[str, str]],
    servers: list[str],
    ceiling_sec: float = 300.0,
) -> dict[str, Any]:
    """`dishes`: name -> {"course", "temperature"} (from data/menu.json)."""
    up: dict[str, float] = {}
    plate_table: dict[str, str] = {}
    plate_dish: dict[str, str] = {}
    left: dict[str, float] = {}
    run_plates: dict[str, list[str]] = defaultdict(list)
    run_tasks: dict[str, int] = defaultdict(int)
    task_ids: set[str] = set()
    task_plates: dict[str, list[str]] = defaultdict(list)
    delivered: dict[str, float] = {}
    escalated: set[str] = set()
    floor_kind: dict[str, str] = {}
    floor_escalated: set[str] = set()
    done_by: dict[str, str] = {}
    idle = dict.fromkeys(servers, 0.0)
    busy = dict.fromkeys(servers, 0.0)
    reserved_since: float | None = None
    reserved_idle: list[str] = []
    reserved_busy: list[str] = []
    reserved_spans = 0
    end = 0.0

    def close_reserved(t: float) -> None:
        if reserved_since is not None:
            for s in reserved_idle:
                idle[s] = idle.get(s, 0.0) + (t - reserved_since)
            for s in reserved_busy:
                busy[s] = busy.get(s, 0.0) + (t - reserved_since)

    for e in events:
        t, kind, d = e["t"], e["type"], e["data"]
        end = max(end, t)
        if kind == "pass.up":
            up[d["plateId"]] = t
            plate_table[d["plateId"]] = d["table"]
            plate_dish[d["plateId"]] = d["dish"]
        elif kind == "pass.run":
            run_plates[d["runId"]] += d["plates"]
            run_tasks[d["runId"]] += 1
            task_ids.add(d["taskId"])
            task_plates[d["taskId"]] += d["plates"]
            for p in d["plates"]:
                left.setdefault(p, t)
        elif kind == "sim.task":
            floor_kind[d["taskId"]] = d["kind"]
        elif kind == "task.escalated":
            (escalated if d["taskId"] in task_ids else floor_escalated).add(d["taskId"])
        elif kind == "task.done":
            done_by[d["taskId"]] = d["assignee"]
            for p in task_plates.get(d["taskId"], []):
                delivered.setdefault(p, t)
        elif kind == "sim.reserved":
            close_reserved(t)
            reserved_idle = list(d["idle"])
            reserved_busy = list(d.get("busy", []))
            reserved_since = t if reserved_idle else None
            reserved_spans += bool(reserved_idle)
    close_reserved(end)

    waits: dict[str, list[float]] = {temp: [] for temp in TEMPERATURES}
    to_table: dict[str, list[float]] = {temp: [] for temp in TEMPERATURES}
    still_up: dict[str, int] = dict.fromkeys(TEMPERATURES, 0)
    ceiling: dict[str, int] = dict.fromkeys(TEMPERATURES, 0)
    for plate, t_up in up.items():
        temp = dishes[plate_dish[plate]]["temperature"]
        if plate not in left:
            still_up[temp] += 1
            continue
        wait = left[plate] - t_up
        if plate in delivered:
            to_table[temp].append(delivered[plate] - t_up)
        waits[temp].append(wait)
        ceiling[temp] += wait > ceiling_sec

    paired = [r for r, ps in run_plates.items() if len({plate_table[p] for p in ps}) >= 2]
    courses = course_spread(up, left, plate_table, plate_dish, dishes)
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for plate in up:
        groups[(plate.rsplit(":", 1)[0], dishes[plate_dish[plate]]["course"])].append(plate)
    hot_after_course_up: list[float] = []
    course_to_table: list[float] = []
    for plates in groups.values():
        last_up = max(up[p] for p in plates)
        if any(dishes[plate_dish[p]]["temperature"] == "hot" for p in plates):
            hot_after_course_up += [
                max(0.0, left[p] - last_up)
                for p in plates
                if p in left and dishes[plate_dish[p]]["temperature"] == "hot"
            ]
            if all(p in delivered for p in plates):
                course_to_table.append(max(delivered[p] for p in plates) - last_up)
    return {
        "serviceEndSec": round(end),
        "plates": len(up),
        "waitSec": {temp: summary(waits[temp]) for temp in TEMPERATURES},
        "allWaitSec": summary([w for ws in waits.values() for w in ws]),
        "toTableSec": {temp: summary(to_table[temp]) for temp in TEMPERATURES},
        "hotWaitAfterCourseUpSec": summary(hot_after_course_up),
        "hotCourseToTableSec": summary(course_to_table),
        "ceilingPlates": {**ceiling, "total": sum(ceiling.values())},
        "stillAtPass": {**still_up, "total": sum(still_up.values())},
        "runs": len(run_plates),
        "runTasks": sum(run_tasks.values()),
        "multiTableRuns": len(paired),
        "escalatedRunTasks": len(escalated),
        "runTasksDoneBy": dict(
            sorted(Counter(done_by[t] for t in task_ids if t in done_by).items())
        ),
        "floorTasks": dict(sorted(Counter(floor_kind.values()).items())),
        "escalatedFloorTasks": len(floor_escalated & floor_kind.keys()),
        "idleReservedSec": {
            "total": round(sum(idle.values())),
            "perServer": {s: round(v) for s, v in idle.items()},
            "emptyHanded": round(sum(idle.values()) - sum(busy.values())),
            "emptyHandedPerServer": {s: round(idle[s] - busy.get(s, 0.0)) for s in idle},
            "spans": reserved_spans,
        },
        "courses": courses,
    }


def course_spread(
    up: dict[str, float],
    left: dict[str, float],
    plate_table: dict[str, str],
    plate_dish: dict[str, str],
    dishes: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Did a table's course leave the pass together? Spread = last plate out - first plate out."""
    by_course: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for plate in up:
        if plate in left:
            order_id = plate.rsplit(":", 1)[0]
            course = dishes[plate_dish[plate]]["course"]
            by_course[(order_id, plate_table[plate], course)].append(left[plate])
    spreads = [max(ts) - min(ts) for ts in by_course.values()]
    together = sum(s == 0 for s in spreads)
    return {
        "n": len(spreads),
        "leftTogether": together,
        "spreadSec": summary(spreads),
    }
