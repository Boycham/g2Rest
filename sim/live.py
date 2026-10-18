"""--live: the same world and runners against a running backend, over HTTP and WebSocket.

For the demo: the Organizer and Kitchen pages show the rush while it plays. Simulated time runs
`speed` times faster than the wall clock; the backend keeps its own real clock, so its timers do
not speed up with it. Start it with the timers scaled down by the same factor and no Gemini key
(sim/README.md has the command). The numbers of record come from the offline run: here events
are stamped from the backend's wall-clock `at` (so client and backend must share a clock), HTTP
round trips cost simulated time, RunWeights decay and the 5-minute ceiling stay in real minutes,
and idle-while-reserved isn't measured.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from websockets.asyncio.client import ClientConnection, connect

import metrics
import scenario
from engine import Action, Runner, World

POLL_SEC = 0.2


class WallScheduler:
    """Simulated seconds = wall seconds x speed; callbacks run as asyncio tasks."""

    def __init__(self, speed: float) -> None:
        self.loop = asyncio.get_running_loop()
        self.t0 = self.loop.time()
        self.wall0 = time.time()
        self.speed = speed
        self.tasks: set[asyncio.Task[None]] = set()
        self.errors: list[BaseException] = []

    def now(self) -> float:
        return (self.loop.time() - self.t0) * self.speed

    def stamp(self, iso: str) -> float:
        """Simulated time of a backend event from its wall-clock `at` (same machine)."""
        return max(0.0, (datetime.fromisoformat(iso).timestamp() - self.wall0) * self.speed)

    def at(self, t: float, fn: Action) -> None:
        self.loop.call_later(max(0.0, (t - self.now()) / self.speed), self._spawn, fn)

    def _spawn(self, fn: Action) -> None:
        task = self.loop.create_task(self._run(fn))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _run(self, fn: Action) -> None:
        try:
            await fn()
        except Exception as e:  # noqa: BLE001 - report every failure at the end, keep playing
            print(f"[fs] live: {type(e).__name__}: {e}")
            self.errors.append(e)


class HttpBackend:
    """The same calls the glasses and the kitchen page make."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        r = await self.http.post(path, json=body or {})
        r.raise_for_status()
        return r.json()

    async def set_status(self, table: str, status: str) -> None:
        await self.post(f"/tables/{table}/status", {"status": status})

    async def fire(self, table: str, lines: list[tuple[int, str]]) -> str:
        order_id = ""
        for seat, dish in lines:
            result = await self.post(
                "/tools/add_item", {"table": table, "seat": seat, "dish": dish}
            )
            if "error" in result:
                raise RuntimeError(f"add_item failed: {result}")
            order_id = result["orderId"]
        await self.post(f"/orders/{order_id}/confirm")
        return order_id

    async def plate_up(self, order_id: str, line: int) -> None:
        await self.post("/pass/up", {"orderId": order_id, "line": line})

    async def create_task(self, kind: str, table: str, notes: list[str]) -> str:
        task = await self.post("/tasks", {"kind": kind, "table": table, "notes": notes})
        return str(task["id"])


async def play(
    scn: dict[str, Any], seed: int, planner: str, url: str, token: str, speed: float
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(base_url=url, headers=headers, timeout=5.0) as http:
        backend = HttpBackend(http)
        await backend.post("/reset")
        await backend.post("/pass/planner", {"planner": planner})
        floor = (await http.get("/floor")).json()
        seen = max([e["seq"] for e in (await http.get("/events")).json()], default=0)

        sched = WallScheduler(speed)
        world = World(
            scenario.build(scn, scenario.load_menu(), seed), floor["tables"], backend, sched
        )
        ws_base = url.replace("http", "ws", 1).rstrip("/") + "/ws?"
        sockets: list[ClientConnection] = []
        readers: list[asyncio.Task[None]] = []
        staff = [(s["id"], "server") for s in floor["servers"]] + [
            (floor["manager"]["id"], "manager")
        ]
        for who, role in staff:
            query = {"role": role, "staff": who} | ({"token": token} if token else {})
            ws = await connect(ws_base + urlencode(query))

            async def send(frame: dict[str, Any], ws: ClientConnection = ws) -> None:
                await ws.send(json.dumps(frame))

            runner = Runner(who, scn, sched, send, random.Random(f"{seed}:{who}"))

            async def read(ws: ClientConnection = ws, runner: Runner = runner) -> None:
                async for raw in ws:
                    runner.on_message(json.loads(raw))

            sockets.append(ws)
            readers.append(asyncio.create_task(read()))

        stream: list[dict[str, Any]] = []
        world.start()
        hard_stop = scn["hard_stop_min"] * 60
        print(f"[fs] live {planner}: playing at x{speed:g}")
        last_report = 0.0
        while not world.finished and sched.now() < hard_stop:
            await asyncio.sleep(POLL_SEC)
            for ev in (await http.get("/events", params={"since": seen})).json():
                seen = ev["seq"]
                e = {"t": sched.stamp(ev["at"]), "type": ev["type"], "data": ev["data"]}
                stream.append(e)
                world.on_backend_event(e)
            stream.extend(world.log)
            world.log.clear()
            if sched.now() - last_report >= 900:
                last_report = sched.now()
                print(
                    f"[fs] live {planner}: {sched.now() / 60:.0f} min, "
                    f"{world.cleared}/{len(world.parties)} parties done"
                )
        stream.append({"t": sched.now(), "type": "sim.end", "data": {"finished": world.finished}})
        for task in readers:
            task.cancel()
        for ws in sockets:
            await ws.close()
        for task in list(sched.tasks):
            task.cancel()
        return {"events": stream, "world": world, "errors": len(sched.errors)}


def run_live(
    scn: dict[str, Any],
    seed: int,
    planners: tuple[str, ...],
    url: str,
    token: str,
    speed: float,
) -> dict[str, Any]:
    dishes = scenario.dish_table(scenario.load_menu())
    servers = [s["id"] for s in scenario.load_floor()["servers"]]
    out: dict[str, Any] = {}
    for planner in planners:
        res = asyncio.run(play(scn, seed, planner, url, token, speed))
        m = metrics.compute(res["events"], dishes, servers)
        m["idleReservedSec"] = {
            "total": None,
            "perServer": dict.fromkeys(servers),
            "emptyHanded": None,
            "note": "not measured in --live",
        }
        m["parties"] = len(res["world"].parties)
        m["served"] = res["world"].left
        m["finished"] = res["world"].finished
        m["liveErrors"] = res["errors"]
        out[planner] = m
        out.setdefault("_events", {})[planner] = res["events"]
    return out
