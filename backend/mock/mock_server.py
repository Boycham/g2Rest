"""Mock backend: replays canned contract messages to every glasses connection.

Stand-in for the real hub so the glasses app can develop against CONTRACT.md today.
No business logic: it replays mock/script.json, echoes task.accept/done/bounce back
as task.updated, and logs everything the glasses send (binary frames as byte counts).

    .venv/bin/python mock/mock_server.py            # ws://localhost:8787/ws
    FS_MOCK_PORT=8788 .venv/bin/python mock/mock_server.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from websockets.asyncio.server import ServerConnection, serve

SCRIPT_PATH = Path(__file__).with_name("script.json")
WIRE_STATE = {"task.accept": "accepted", "task.done": "done", "task.bounce": "bounced"}


def log(*parts: Any) -> None:
    print("[fs-mock]", *parts, flush=True)


def load_script() -> list[dict[str, Any]]:
    steps = json.loads(SCRIPT_PATH.read_text())["steps"]
    return sorted(steps, key=lambda s: s["delayMs"])


async def replay(ws: ServerConnection, tasks: dict[str, dict[str, Any]]) -> None:
    started = asyncio.get_running_loop().time()
    for step in load_script():
        wait = started + step["delayMs"] / 1000 - asyncio.get_running_loop().time()
        if wait > 0:
            await asyncio.sleep(wait)
        msg = step["message"]
        if msg["type"] in ("task.assigned", "task.updated"):
            tasks[msg["task"]["id"]] = msg["task"]
        await ws.send(json.dumps(msg))
        log("->", msg["type"], msg.get("task", {}).get("id", msg.get("id", "")))


async def handle_glasses(ws: ServerConnection, raw: str | bytes, tasks: dict[str, Any]) -> None:
    if isinstance(raw, bytes):
        log("<- capture.audio", f"{len(raw)} bytes")
        return
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        log("<- INVALID", raw[:200])
        return
    log("<-", raw[:200])
    state = WIRE_STATE.get(msg.get("type"))
    task = tasks.get(msg.get("taskId", ""))
    if state and task:
        task = {**task, "state": state}
        tasks[task["id"]] = task
        await ws.send(json.dumps({"type": "task.updated", "task": task}))
        log("-> task.updated", task["id"], state)


async def session(ws: ServerConnection) -> None:
    path = ws.request.path if ws.request else "?"
    if not path.startswith("/ws"):
        await ws.close(code=4404, reason="use /ws")
        return
    log("glasses connected", path)
    tasks: dict[str, dict[str, Any]] = {}
    player = asyncio.create_task(replay(ws, tasks))
    try:
        async for raw in ws:
            await handle_glasses(ws, raw, tasks)
    finally:
        player.cancel()
        log("glasses disconnected")


async def main() -> None:
    port = int(os.environ.get("FS_MOCK_PORT", "8787"))
    async with serve(session, "0.0.0.0", port):
        log(f"mock backend on ws://localhost:{port}/ws, replaying {SCRIPT_PATH.name}")
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
