"""Mock servers for the routing demo: other people on the floor, each on a real staff socket.

The owner wears the real G2 as s1 (Ava). Each mock opens `/ws?token=&role=server&staff=<id>` like
the glasses, so `GET /health` lists it online and the router (Gemini, or the rules) can pick it.
A mock reads its cards and answers like a person would: accept after a few seconds, finish after
a kind-based work time, sometimes decline first (the task walks the escalation chain) and
sometimes hold one past `FS_DONE_SEC` (the manager's slow warning and a reroute). Each mock has its
own speed, so `GET /stats` shows real differences for Gemini to weigh. `--dispatch-every N` also
posts a demo task every N seconds through the router. s1 is never mocked and never acted on.

    cd sim && ../backend/.venv/bin/python mock_staff.py --api http://localhost:8818 --staff s2,s3,s4

Start the backend with `FS_FLOOR=demo` (data/floor.demo.json: Ben, Cam and Dee besides Ava).
Ctrl-C closes every socket, so the mocks show offline again. Details: sim/README.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import signal
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlencode

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus

HUMAN = "s1"  # the owner's real G2: never mocked, never acted on
WORK_SEC: dict[str, tuple[float, float]] = {
    "RUN": (20, 40),  # to the table and back
    "CHECK": (15, 15),
    "CLEAR": (20, 30),
    "ORDER": (30, 50),
    "SEAT": (10, 20),
}
SPEEDS = (0.7, 1.0, 1.4)  # work-time factor per mock in --staff order: Ben fast, Cam, Dee slow
DISPATCH_KINDS = ("CHECK", "CLEAR", "ORDER", "SEAT", "RUN")
RECONNECT_SEC = 2.0
T0 = time.monotonic()

Send = Callable[[dict[str, Any]], Awaitable[None]]


def log(who: str, what: str) -> None:
    print(f"[fs-mock] {time.monotonic() - T0:6.1f}s {who:<5} {what}", flush=True)


@dataclass(frozen=True)
class Profile:
    """How one mock behaves. Times are seconds; `speed` scales the work times only."""

    speed: float = 1.0
    accept_sec: tuple[float, float] = (3.0, 10.0)
    bounce_share: float = 0.1  # cards declined (task.bounce) before accepting, once per task
    slow_share: float = 0.1  # accepted tasks held past the backend's doneSec
    slow_extra_sec: float = 15.0  # how far past doneSec a slow task is held
    work_sec: dict[str, tuple[float, float]] = field(default_factory=lambda: dict(WORK_SEC))
    time_scale: float = 1.0  # multiplies accept and work times (tests, quick rehearsals)

    def work(self, kind: str, rng: random.Random) -> float:
        lo, hi = self.work_sec.get(kind, (15.0, 30.0))
        return rng.uniform(lo, hi) * self.speed * self.time_scale

    def accept_delay(self, rng: random.Random) -> float:
        return rng.uniform(*self.accept_sec) * self.time_scale


def label(task: dict[str, Any]) -> str:
    return f"{task['id']} {task['kind']} {task['table']}"


class MockServer:
    """One mock server's hands: every card gets its own timeline (accept, work, done)."""

    def __init__(
        self,
        staff: str,
        name: str,
        profile: Profile,
        rng: random.Random,
        done_sec: float,
        can_bounce: bool = True,
    ) -> None:
        if staff == HUMAN:
            raise ValueError(f"{HUMAN} is the real glasses; never mock it")
        self.staff, self.name, self.profile, self.rng = staff, name, profile, rng
        self.done_sec = done_sec
        self.can_bounce = can_bounce  # off when no other mock would get the bounce
        self.timers: dict[str, asyncio.Task[None]] = {}
        self.bounced: set[str] = set()  # declined once already: take it if it comes back
        self.send: Send | None = None

    def handle(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        task = msg.get("task") or {}
        if kind == "task.assigned":
            if task.get("assignee") != self.staff or task["id"] in self.timers:
                return
            self.timers[task["id"]] = asyncio.create_task(self._card(task))
        elif kind == "task.updated" and task.get("state") in ("bounced", "done"):
            timer = self.timers.pop(task["id"], None)
            if timer is not None:
                timer.cancel()
                if task["state"] == "bounced":
                    log(self.name, f"lost   {label(task)} (moved to someone else)")
        elif kind == "task.rejected":
            log(self.name, f"refused {msg.get('action')} {msg.get('taskId')}: {msg.get('reason')}")
            timer = self.timers.pop(str(msg.get("taskId")), None)
            if timer is not None:
                timer.cancel()

    async def _send(self, frame: dict[str, Any]) -> None:
        if self.send is not None:
            await self.send(frame)

    async def _card(self, task: dict[str, Any]) -> None:
        tid, p = task["id"], self.profile
        try:
            if task.get("state") != "accepted":
                wait = p.accept_delay(self.rng)
                await asyncio.sleep(wait)
                if (
                    self.can_bounce
                    and tid not in self.bounced
                    and self.rng.random() < p.bounce_share
                ):
                    self.bounced.add(tid)
                    log(self.name, f"bounce {label(task)} (after {wait:.1f} s)")
                    self.timers.pop(tid, None)
                    await self._send({"type": "task.bounce", "taskId": tid})
                    return
                await self._send({"type": "task.accept", "taskId": tid})
                log(self.name, f"accept {label(task)} (after {wait:.1f} s)")
            slow = self.rng.random() < p.slow_share
            work = self.done_sec + p.slow_extra_sec if slow else p.work(task["kind"], self.rng)
            if slow:
                note = "flagged, keeps it" if task["kind"] == "RUN" else "expect a reroute"
                log(self.name, f"slow   {label(task)} (holding {work:.0f} s, {note})")
            await asyncio.sleep(work)
            self.timers.pop(tid, None)
            await self._send({"type": "task.done", "taskId": tid})
            log(self.name, f"done   {label(task)} (worked {work:.1f} s)")
        except asyncio.CancelledError:
            pass
        except ConnectionClosed:
            self.timers.pop(tid, None)

    def cancel_all(self) -> None:
        for timer in self.timers.values():
            timer.cancel()
        self.timers.clear()

    async def run(self, ws_url: str, stop: asyncio.Event) -> None:
        """Hold the socket until `stop`; reconnect if the backend restarts."""
        while not stop.is_set():
            try:
                async with connect(ws_url) as ws:

                    async def send(frame: dict[str, Any]) -> None:
                        await ws.send(json.dumps(frame))

                    self.send = send
                    log(self.name, f"online as {self.staff}")
                    reader = asyncio.create_task(self._read(ws))
                    stopper = asyncio.create_task(stop.wait())
                    await asyncio.wait({reader, stopper}, return_when=asyncio.FIRST_COMPLETED)
                    stopper.cancel()
                    if stop.is_set():
                        reader.cancel()
                        self.cancel_all()
                        await ws.close()
                        log(self.name, "offline (socket closed)")
                        return
                    log(self.name, "socket dropped, reconnecting")
            except (OSError, InvalidHandshake) as e:
                if isinstance(e, InvalidStatus) and e.response.status_code == 401:
                    raise
                log(self.name, f"can't connect ({type(e).__name__}), retrying")
            finally:
                self.send = None
            try:
                await asyncio.wait_for(stop.wait(), RECONNECT_SEC)
            except TimeoutError:
                pass

    async def _read(self, ws: Any) -> None:
        try:
            async for raw in ws:
                if isinstance(raw, str):
                    self.handle(json.loads(raw))
        except ConnectionClosed as e:
            if e.rcvd is not None and e.rcvd.code == 4401:
                log(self.name, "bad token (4401)")


def dispatch_tables(floor: dict[str, Any], mocks: list[str]) -> list[str]:
    """Tables whose section belongs to a mock, so demo tasks don't land on Ava's glasses first."""
    sections = {s["id"] for s in floor["sections"] if s["server"] in mocks}
    return [t["id"] for t in floor["tables"] if t["section"] in sections]


def demo_task(kind: str, table: str, menu: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    body: dict[str, Any] = {"kind": kind, "table": table}
    if kind == "RUN":
        dish = rng.choice(menu["dishes"])
        short = (dish.get("aliases") or [dish["name"].lower()])[0]
        body["items"] = [{"qty": rng.randint(1, 2), "dish": short, "seats": [1]}]
    return body


async def dispatch_loop(
    http: httpx.AsyncClient,
    every: float,
    tables: list[str],
    names: dict[str, str],
    rng: random.Random,
    stop: asyncio.Event,
) -> None:
    menu = (await http.get("/menu")).json()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), every)
            return
        except TimeoutError:
            pass
        body = demo_task(rng.choice(DISPATCH_KINDS), rng.choice(tables), menu, rng)
        try:
            r = await http.post("/tasks", json=body)
            r.raise_for_status()
            task = r.json()
            who = task["assignee"]
            tag = " (the real glasses)" if who == HUMAN else ""
            log("org", f"dispatch {label(task)} -> {names.get(who, who)}{tag}")
        except httpx.HTTPError as e:
            log("org", f"dispatch {body['kind']} {body['table']} failed: {e!r}")


async def run_mocks(
    api: str,
    token: str,
    staff: list[str] | None,
    profiles: dict[str, Profile],
    stop: asyncio.Event,
    *,
    seed: int | None = None,
    dispatch_every: float = 0.0,
    tables: list[str] | None = None,
) -> list[MockServer]:
    """Run the mocks (and the optional dispatcher) until `stop` is set."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(base_url=api, headers=headers, timeout=5.0) as http:
        floor = (await http.get("/floor")).json()
        stats = (await http.get("/stats")).json()
        servers = {s["id"]: s["name"] for s in floor["servers"]}
        staff = staff or [s for s in servers if s != HUMAN]
        if HUMAN in staff:
            raise ValueError(f"{HUMAN} ({servers.get(HUMAN)}) is the real glasses; never mock it")
        unknown = [s for s in staff if s not in servers]
        if unknown:
            raise ValueError(f"not servers on this floor: {unknown} (FS_FLOOR=demo for s3, s4)")
        if not staff:
            raise ValueError("no servers to mock: start the backend with FS_FLOOR=demo")
        rng = random.Random(seed)
        mocks = [
            MockServer(
                s,
                servers[s],
                profiles.get(s, Profile(speed=SPEEDS[i % len(SPEEDS)])),
                random.Random(rng.random()),
                float(stats["doneSec"]),
                can_bounce=len(staff) > 1,
            )
            for i, s in enumerate(staff)
        ]
        for m in mocks:
            p = m.profile
            log(
                m.name,
                f"{m.staff}: speed x{p.speed:g}, accept {p.accept_sec[0]:g}-{p.accept_sec[1]:g} s, "
                f"bounce {p.bounce_share:.0%}, slow {p.slow_share:.0%}"
                + (f", times x{p.time_scale:g}" if p.time_scale != 1 else ""),
            )
        ws_base = api.replace("http", "ws", 1).rstrip("/") + "/ws?"
        jobs = [
            asyncio.create_task(
                m.run(
                    ws_base
                    + urlencode(
                        {"role": "server", "staff": m.staff} | ({"token": token} if token else {})
                    ),
                    stop,
                )
            )
            for m in mocks
        ]
        if dispatch_every > 0:
            pick = tables or dispatch_tables(floor, staff)
            jobs.append(
                asyncio.create_task(
                    dispatch_loop(
                        http, dispatch_every, pick, servers, random.Random(rng.random()), stop
                    )
                )
            )
        try:
            await asyncio.gather(*jobs)
        finally:
            stop.set()
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
    return mocks


def parse_speeds(text: str) -> dict[str, float]:
    """`s2=0.7,s4=1.5` -> {"s2": 0.7, "s4": 1.5}."""
    out: dict[str, float] = {}
    for part in filter(None, (p.strip() for p in text.split(","))):
        who, _, value = part.partition("=")
        out[who.strip()] = float(value)
    return out


def parse_range(text: str) -> tuple[float, float]:
    lo, _, hi = text.partition(",")
    return float(lo), float(hi or lo)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8787", help="backend base URL")
    ap.add_argument("--token", default=os.environ.get("FS_TOKEN", ""), help="FS_TOKEN (env)")
    ap.add_argument("--staff", default="", help="ids to mock, e.g. s2,s3,s4 (default: all but s1)")
    ap.add_argument("--speed", default="", help="work-time factor per mock, e.g. s2=0.7,s4=1.5")
    ap.add_argument("--accept-sec", default="3,10", help="accept after lo,hi seconds")
    ap.add_argument("--bounce-share", type=float, default=0.15, help="cards declined first")
    ap.add_argument("--slow-share", type=float, default=0.1, help="tasks held past doneSec")
    ap.add_argument("--time-scale", type=float, default=1.0, help="multiply accept + work times")
    ap.add_argument("--dispatch-every", type=float, default=0.0, help="post a demo task every N s")
    ap.add_argument("--tables", default="", help="tables for --dispatch-every (default: mocks')")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    staff = [s.strip() for s in args.staff.split(",") if s.strip()] or None
    speeds = parse_speeds(args.speed)
    base = Profile(
        accept_sec=parse_range(args.accept_sec),
        bounce_share=args.bounce_share,
        slow_share=args.slow_share,
        time_scale=args.time_scale,
    )
    order = staff or [f"s{i}" for i in range(2, 10)]
    profiles = {
        s: replace(base, speed=speeds.get(s, SPEEDS[i % len(SPEEDS)])) for i, s in enumerate(order)
    }
    tables = [t.strip() for t in args.tables.split(",") if t.strip()] or None

    async def go() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await run_mocks(
            args.api,
            args.token,
            staff,
            profiles,
            stop,
            seed=args.seed,
            dispatch_every=args.dispatch_every,
            tables=tables,
        )

    try:
        asyncio.run(go())
    except ValueError as e:
        raise SystemExit(f"[fs-mock] {e}") from None


if __name__ == "__main__":
    main()
