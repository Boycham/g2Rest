"""Step 3 "done" check: create tasks and watch them move through every state.

Run the backend with a short escalation first, then this script:

    FS_TOKEN=dev FS_ESCALATION_SEC=2 .venv/bin/uvicorn app.main:app --port 8787
    FS_TOKEN=dev .venv/bin/python scripts/task_walkthrough.py

It opens sockets for s1, s2 and the manager, and prints every message each one receives,
then checks the event log shows queued -> sent -> accepted -> done, a bounce, and the
escalation chain s1 -> s2 -> m1 -> alert.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

import httpx
from websockets.asyncio.client import connect

BASE = os.environ.get("FS_BASE", "http://localhost:8787")
WS = BASE.replace("http", "ws", 1) + "/ws"
TOKEN = os.environ.get("FS_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
T0 = time.monotonic()


def say(who: str, text: str) -> None:
    print(f"[fs-walk] {time.monotonic() - T0:6.2f}s {who:<4} {text}", flush=True)


async def listen(name: str, ws: Any, inbox: asyncio.Queue[dict[str, Any]]) -> None:
    async for raw in ws:
        msg = json.loads(raw)
        detail = (
            f"{msg['task']['id']} {msg['task']['state']}"
            if "task" in msg
            else json.dumps({k: v for k, v in msg.items() if k != "type"})[:90]
        )
        say(name, f"<- {msg['type']} {detail}")
        await inbox.put(msg)


async def expect(
    inbox: asyncio.Queue[dict[str, Any]], type_: str, state: str | None = None
) -> dict:
    while True:
        msg = await asyncio.wait_for(inbox.get(), 15)
        if msg["type"] == type_ and (state is None or msg.get("task", {}).get("state") == state):
            return msg


async def main() -> int:
    async with httpx.AsyncClient(base_url=BASE, headers=HEADERS, timeout=5) as http:
        health = (await http.get("/health")).json()
        say("http", f"health {health}")
        await http.post("/reset")
        inboxes = {n: asyncio.Queue() for n in ("s1", "s2", "m1")}
        urls = {
            "s1": f"{WS}?token={TOKEN}&role=server&staff=s1",
            "s2": f"{WS}?token={TOKEN}&role=server&staff=s2",
            "m1": f"{WS}?token={TOKEN}&role=manager&staff=m1",
        }
        socks = {n: await connect(u) for n, u in urls.items()}
        listeners = [asyncio.create_task(listen(n, s, inboxes[n])) for n, s in socks.items()]

        async def gesture(name: str, type_: str, task_id: str) -> None:
            say(name, f"-> {type_}")
            await socks[name].send(json.dumps({"type": type_, "taskId": task_id}))

        # 1. happy path: queued -> sent -> accepted -> done
        task = (
            await http.post(
                "/tasks",
                json={
                    "kind": "RUN",
                    "table": "T2",
                    "items": [{"qty": 2, "dish": "halibut", "seats": [1, 3]}],
                    "allergies": [{"allergen": "SHELLFISH", "seats": [3]}],
                },
            )
        ).json()
        say("http", f"created {task['id']} -> {task['assignee']} ({task['backendState']})")
        await expect(inboxes["s1"], "task.assigned")
        await gesture("s1", "task.accept", task["id"])
        await expect(inboxes["s1"], "task.updated", "accepted")
        await gesture("s1", "task.done", task["id"])
        await expect(inboxes["s1"], "task.updated", "done")

        # 2. bounce: s1 passes it to s2, who finishes it
        task2 = (await http.post("/tasks", json={"kind": "CLEAR", "table": "T3"})).json()
        await expect(inboxes["s1"], "task.assigned")
        await gesture("s1", "task.bounce", task2["id"])
        await expect(inboxes["s1"], "task.updated", "bounced")
        await expect(inboxes["s2"], "task.assigned")
        await gesture("s2", "task.accept", task2["id"])
        await gesture("s2", "task.done", task2["id"])
        await expect(inboxes["s2"], "task.updated", "done")

        # 3. escalation: nobody accepts; s1 -> s2 -> manager -> alert; manager finishes it
        task3 = (await http.post("/tasks", json={"kind": "CHECK", "table": "T4"})).json()
        await expect(inboxes["s1"], "task.assigned")
        await expect(inboxes["s1"], "task.updated", "bounced")
        await expect(inboxes["s2"], "task.assigned")
        await expect(inboxes["s2"], "task.updated", "bounced")
        await expect(inboxes["m1"], "task.assigned")
        alert = await expect(inboxes["m1"], "alert")
        await gesture("m1", "task.done", task3["id"])
        await expect(inboxes["m1"], "task.updated", "done")
        cleared = await expect(inboxes["m1"], "alert")
        assert cleared.get("cleared") is True, cleared

        for lst in listeners:
            lst.cancel()
        for s in socks.values():
            await s.close()

        events = (await http.get("/events")).json()
        tasks = {t["id"]: t for t in (await http.get("/tasks")).json()}
        path = [h["to"] for h in tasks[task["id"]]["history"]]
        bounce_path = [h["to"] for h in tasks[task2["id"]]["history"]]
        esc = tasks[task3["id"]]
        checks = {
            "happy path": path == ["queued", "sent", "accepted", "done"],
            "bounce": "bounced" in bounce_path and tasks[task2["id"]]["tried"] == ["s1", "s2"],
            "escalation chain": esc["tried"] == ["s1", "s2", "m1"]
            and [h["to"] for h in esc["history"]].count("escalated") == 2,
            "alert raised and cleared": alert["id"] == f"unacked-{task3['id']}"
            and any(e["type"] == "alert.cleared" for e in events),
            "event log append-only": [e["seq"] for e in events] == list(range(1, len(events) + 1)),
        }
        for name, ok in checks.items():
            say("chk", f"{'PASS' if ok else 'FAIL'} {name}")
        say(
            "chk",
            f"{len(events)} events; escalation task history: {[h['to'] for h in esc['history']]}",
        )
        return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
