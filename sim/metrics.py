"""Pass metrics from a time-stamped event stream, the same for the offline and the live run.

An event is `{"t": seconds since service start, "type": ..., "data": {...}}`: the backend's own
event log (`pass.up`, `pass.run`, `task.*`) stamped with the simulated clock, plus the
simulator's `sim.reserved {idle: [server], runners, plates}` records, written whenever the set of
servers held idle for a bigger run changes (`idle: []` when it ends).

Hot-plate wait is `pass.up` to `pass.run` for each plate, split by the dish's temperature.
"""

from __future__ import annotations

import math
from collections import defaultdict
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
    escalated: set[str] = set()
    idle = dict.fromkeys(servers, 0.0)
    reserved_since: float | None = None
    reserved_idle: list[str] = []
    reserved_spans = 0
    end = 0.0

    def close_reserved(t: float) -> None:
        if reserved_since is not None:
            for s in reserved_idle:
                idle[s] = idle.get(s, 0.0) + (t - reserved_since)

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
            for p in d["plates"]:
                left.setdefault(p, t)
        elif kind == "task.escalated" and d["taskId"] in task_ids:
            escalated.add(d["taskId"])
        elif kind == "sim.reserved":
            close_reserved(t)
            reserved_idle = list(d["idle"])
            reserved_since = t if reserved_idle else None
            reserved_spans += bool(reserved_idle)
    close_reserved(end)

    waits: dict[str, list[float]] = {temp: [] for temp in TEMPERATURES}
    still_up: dict[str, int] = dict.fromkeys(TEMPERATURES, 0)
    ceiling: dict[str, int] = dict.fromkeys(TEMPERATURES, 0)
    for plate, t_up in up.items():
        temp = dishes[plate_dish[plate]]["temperature"]
        if plate not in left:
            still_up[temp] += 1
            continue
        wait = left[plate] - t_up
        waits[temp].append(wait)
        ceiling[temp] += wait > ceiling_sec

    paired = [r for r, ps in run_plates.items() if len({plate_table[p] for p in ps}) >= 2]
    courses = course_spread(up, left, plate_table, plate_dish, dishes)
    return {
        "serviceEndSec": round(end),
        "plates": len(up),
        "waitSec": {temp: summary(waits[temp]) for temp in TEMPERATURES},
        "allWaitSec": summary([w for ws in waits.values() for w in ws]),
        "ceilingPlates": {**ceiling, "total": sum(ceiling.values())},
        "stillAtPass": {**still_up, "total": sum(still_up.values())},
        "runs": len(run_plates),
        "runTasks": sum(run_tasks.values()),
        "multiTableRuns": len(paired),
        "escalatedRunTasks": len(escalated),
        "idleReservedSec": {
            "total": round(sum(idle.values())),
            "perServer": {s: round(v) for s, v in idle.items()},
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
