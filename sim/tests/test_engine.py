"""A tiny hand-made service through the real Store, Hub and TaskBook on the fake clock."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import metrics
import scenario
from engine import run_offline
from scenario import Party

SCN = scenario.load()
MENU = scenario.load_menu()
DISHES = scenario.dish_table(MENU)


def first(course: str, temperature: str) -> str:
    return next(
        n for n, d in DISHES.items() if d["course"] == course and d["temperature"] == temperature
    )


def party(pid: str, arrive: float, size: int) -> Party:
    sec = {key: 60.0 for key in SCN["minutes"]}
    dishes: dict[str, list[tuple[int, str]]] = {
        "appetizer": [(1, first("appetizer", "cold"))],
        "main": [(s, first("main", "hot")) for s in range(1, size + 1)],
        "dessert": [(1, first("dessert", "cold"))],
    }
    jitter = {c: [5.0 * i for i in range(len(v))] for c, v in dishes.items()}
    return Party(pid, arrive, size, dishes, sec, jitter)


def run(planner: str) -> tuple[list[dict[str, Any]], Any]:
    parties = [party("P01", 0.0, 2), party("P02", 30.0, 4)]
    res = asyncio.run(run_offline(SCN, parties, planner, seed=7))
    return res.events, res.world


def test_tiny_service_finishes_and_every_plate_reaches_its_table() -> None:
    for planner in ("fifo", "priority"):
        events, world = run(planner)
        assert world.finished, planner
        m = metrics.compute(events, DISHES, ["s1", "s2"])
        assert m["plates"] == (1 + 2 + 1) + (1 + 4 + 1)  # appetizer, a main per seat, dessert
        assert m["stillAtPass"]["total"] == 0
        assert sum(s["n"] for s in m["toTableSec"].values()) == m["plates"]
        kinds = m["floorTasks"]
        assert kinds == {"CHECK": 2, "CLEAR": 2, "DESSERT_ORDER": 2, "ORDER": 2}


def test_runners_take_reaction_and_travel_time() -> None:
    events, _ = run("priority")
    r = SCN["runner"]
    sent: dict[str, float] = {}
    accepted: dict[str, float] = {}
    runs = {e["data"]["taskId"] for e in events if e["type"] == "pass.run"}
    for e in events:
        tid = e["data"].get("taskId")
        if tid not in runs:
            continue
        if e["type"] == "task.sent":
            sent[tid] = e["t"]
        elif e["type"] == "task.accepted":
            accepted[tid] = e["t"]
            assert e["t"] - sent[tid] >= r["reaction_sec"][0]
        elif e["type"] == "task.done":
            assert e["t"] - accepted[tid] >= r["travel_sec"][0]


def test_priority_sends_a_course_together_fifo_does_not_wait() -> None:
    fifo, _ = run("fifo")
    prio, _ = run("priority")
    mf = metrics.compute(fifo, DISHES, ["s1", "s2"])
    mp = metrics.compute(prio, DISHES, ["s1", "s2"])
    assert mp["courses"]["leftTogether"] == mp["courses"]["n"]
    assert mf["courses"]["leftTogether"] < mf["courses"]["n"]


def test_same_seed_same_numbers() -> None:
    """Task and order ids are random uuids; times, event order and metrics are not."""
    a, _ = run("priority")
    b, _ = run("priority")
    assert [(e["t"], e["type"]) for e in a] == [(e["t"], e["type"]) for e in b]
    ma, mb = (metrics.compute(x, DISHES, ["s1", "s2"]) for x in (a, b))
    assert json.dumps(ma) == json.dumps(mb)
