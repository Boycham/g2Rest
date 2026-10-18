"""Step 10 numbers: what the Tiger Data copy and Sentry cost the hub.

Run the backend (with or without DATABASE_URL / SENTRY_DSN_BACKEND), then this script:

    FS_TOKEN=dev .venv/bin/uvicorn app.main:app --port 8787
    FS_TOKEN=dev .venv/bin/python scripts/measure_observability.py 200

For N tasks it times POST /tasks -> task.assigned on s1's socket (dispatch + delivery) and
task.accept -> task.updated and task.done -> task.updated (the socket round trip through the hub),
then prints the medians/p95s and the eventDb part of GET /health (batch write latency).
`append_cost()` times EventLog.append in-process with and without the EventDB listener.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time

import httpx
from websockets.asyncio.client import connect

BASE = os.environ.get("FS_BASE", "http://localhost:8787")
WS = BASE.replace("http", "ws", 1) + "/ws"
TOKEN = os.environ.get("FS_TOKEN", "")
H = {"Authorization": f"Bearer {TOKEN}"}


def summary(name: str, ms: list[float]) -> str:
    ms = sorted(ms)
    p95 = ms[min(len(ms) - 1, int(0.95 * len(ms)))]
    return f"{name:<22} n={len(ms):<4} median {statistics.median(ms):6.2f} ms  p95 {p95:6.2f} ms"


async def until(ws, task_id: str, state: str) -> None:  # noqa: ANN001
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("task", {}).get("id") == task_id and msg["task"]["state"] == state:
            return


async def run(n: int) -> None:
    dispatch, accept, done = [], [], []
    async with httpx.AsyncClient(base_url=BASE, headers=H, timeout=10) as http:
        await http.post("/reset", json={})
        async with connect(f"{WS}?token={TOKEN}&role=server&staff=s1") as ws:
            for _ in range(n):
                t0 = time.perf_counter()
                r = await http.post(
                    "/tasks", json={"kind": "CHECK", "table": "T1", "assignee": "s1"}
                )
                tid = r.json()["id"]
                await until(ws, tid, "assigned")
                dispatch.append((time.perf_counter() - t0) * 1000)
                for frame, state, out in (
                    ("task.accept", "accepted", accept),
                    ("task.done", "done", done),
                ):
                    t0 = time.perf_counter()
                    await ws.send(json.dumps({"type": frame, "taskId": tid}))
                    await until(ws, tid, state)
                    out.append((time.perf_counter() - t0) * 1000)
        await asyncio.sleep(1.0)  # let the writer drain
        health = (await http.get("/health")).json()
    print(summary("POST /tasks->assigned", dispatch))
    print(summary("accept->updated", accept))
    print(summary("done->updated", done))
    print("eventDb", json.dumps(health.get("eventDb")), "sentry", health.get("sentry"))


def append_cost(n: int = 100_000) -> None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.eventdb import EventDB
    from app.events import EventLog

    async def never() -> None:
        raise OSError

    for label, listeners in (("no listener", []), ("EventDB.offer", [EventDB(never).offer])):
        log = EventLog(listeners=listeners)
        t0 = time.perf_counter()
        for i in range(n):
            log.append("task.accepted", taskId=f"t{i}", table="T1", assignee="s1", acceptSec=1.0)
        print(f"EventLog.append, {label:<14} {(time.perf_counter() - t0) / n * 1e6:.2f} us")


if __name__ == "__main__":
    append_cost()
    asyncio.run(run(int(sys.argv[1]) if len(sys.argv) > 1 else 200))
