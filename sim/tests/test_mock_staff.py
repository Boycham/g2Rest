"""Mock servers against an in-process backend (uvicorn on a free port, demo floor)."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import uvicorn
from app.config import DATA_DIR, Settings
from app.main import create_app

import mock_staff
from mock_staff import HUMAN, MockServer, Profile, dispatch_tables, run_mocks

TOKEN = "t"
H = {"Authorization": f"Bearer {TOKEN}"}
FAST = Profile(accept_sec=(0.05, 0.1), bounce_share=0.0, slow_share=0.0, time_scale=0.01)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def api() -> Iterator[str]:
    settings = Settings(
        token=TOKEN,
        escalation_sec=30,
        done_sec=0.6,
        data_dir=DATA_DIR,
        floor_file="floor.demo.json",
    )
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


async def until(check: Any, timeout: float = 5.0) -> Any:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if result := await check():
            return result
        await asyncio.sleep(0.05)
    raise AssertionError("timed out")


async def scenario(api: str, staff: list[str], profiles: dict[str, Profile], body: dict) -> Any:
    """Start the mocks, wait until they are online, post one task, wait for it to finish."""
    stop = asyncio.Event()
    mocks = asyncio.create_task(run_mocks(api, TOKEN, staff, profiles, stop, seed=1))
    async with httpx.AsyncClient(base_url=api, headers=H) as http:

        async def online() -> bool:
            return set(staff) <= set((await http.get("/health")).json()["online"])

        await until(online)
        task_id = (await http.post("/tasks", json=body)).json()["id"]

        async def finished() -> dict | None:
            tasks = {t["id"]: t for t in (await http.get("/tasks")).json()}
            return tasks[task_id] if tasks[task_id]["backendState"] == "done" else None

        task = await until(finished)
        events = (await http.get("/events")).json()
        stats = (await http.get("/stats")).json()
        stop.set()
        await mocks
        health = (await http.get("/health")).json()
    moves = [
        (e["data"]["to"], e["data"].get("assignee"))
        for e in events
        if e["type"].startswith("task.") and "to" in e["data"] and e["data"]["taskId"] == task_id
    ]
    return task, moves, stats, health


def test_mock_accepts_then_finishes_and_goes_offline_on_stop(api: str) -> None:
    body = {"kind": "CHECK", "table": "T5", "assignee": "s2"}
    task, moves, stats, health = asyncio.run(scenario(api, ["s2"], {"s2": FAST}, body))
    assert task["assignee"] == "s2"
    assert [m for m in moves if m[0] in ("accepted", "done")] == [
        ("accepted", "s2"),
        ("done", "s2"),
    ]
    ben = next(s for s in stats["servers"] if s["id"] == "s2")
    assert ben["done"] == 1 and "CHECK" in ben["avgSecByKind"]
    assert health["online"] == []  # stop closed the socket


def test_bounce_moves_the_card_to_the_next_mock_who_finishes_it(api: str) -> None:
    profiles = {"s2": Profile(**{**FAST.__dict__, "bounce_share": 1.0}), "s3": FAST}
    body = {"kind": "CLEAR", "table": "T5", "assignee": "s2"}  # section B: s2, then s3
    task, moves, _, _ = asyncio.run(scenario(api, ["s2", "s3"], profiles, body))
    assert task["assignee"] == "s3"
    assert ("bounced", "s2") in moves
    assert [m for m in moves if m[0] in ("accepted", "done")] == [
        ("accepted", "s3"),
        ("done", "s3"),
    ]


def test_slow_mock_triggers_the_reroute_and_the_next_one_finishes(api: str) -> None:
    slow = Profile(**{**FAST.__dict__, "slow_share": 1.0, "slow_extra_sec": 30.0})
    body = {"kind": "CHECK", "table": "T3", "assignee": "s3"}  # section C: s3, then s2
    task, moves, _, _ = asyncio.run(scenario(api, ["s3", "s2"], {"s3": slow, "s2": FAST}, body))
    assert task["assignee"] == "s2"
    assert ("escalated", "s3") in moves  # held past done_sec (0.6 s), moved by the backend
    assert moves[-1] == ("done", "s2")


def test_s1_is_never_mocked(api: str) -> None:
    with pytest.raises(ValueError, match="real glasses"):
        asyncio.run(run_mocks(api, TOKEN, ["s2", HUMAN], {}, asyncio.Event()))
    with pytest.raises(ValueError):
        MockServer(HUMAN, "Ava", FAST, mock_staff.random.Random(1), 300)


def test_mock_ignores_cards_that_are_not_its_own() -> None:
    async def go() -> dict[str, Any]:
        m = MockServer("s2", "Ben", FAST, mock_staff.random.Random(1), 300)
        task = {"id": "task-1", "kind": "RUN", "table": "T1", "state": "assigned"}
        m.handle({"type": "task.assigned", "task": {**task, "assignee": HUMAN}})
        before = dict(m.timers)
        m.handle({"type": "task.assigned", "task": {**task, "assignee": "s2"}})
        m.handle({"type": "task.rejected", "taskId": "task-1", "action": "accept", "reason": "x"})
        return {"before": before, "after": dict(m.timers)}

    out = asyncio.run(go())
    assert out == {"before": {}, "after": {}}


def test_dispatch_tables_skip_ava_and_tasks_are_valid() -> None:
    floor = mock_staff.json.loads((DATA_DIR / "floor.demo.json").read_text())
    floor["sections"] = [{"id": s["id"], "server": s["server"]} for s in floor["sections"]]
    assert dispatch_tables(floor, ["s2", "s3", "s4"]) == ["T3", "T4", "T5", "T6", "T7", "T8"]
    assert dispatch_tables(floor, ["s3"]) == ["T3", "T4"]
    menu = mock_staff.json.loads((DATA_DIR / "menu.json").read_text())
    run = mock_staff.demo_task("RUN", "T3", menu, mock_staff.random.Random(1))
    assert run["items"][0]["qty"] in (1, 2) and run["items"][0]["seats"] == [1]
