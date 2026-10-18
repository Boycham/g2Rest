"""The dinner-rush world and its offline run on the real backend, on a simulated clock.

`World` plays the guests and the kitchen: parties arrive, wait for a table that fits, order,
eat, pay and leave; the kitchen puts plates up at the pass. The floor work around a meal goes
through the backend as real tasks: an ORDER task when a table is ready to order (the order is
sent when it's done), another for desserts, a CHECK task to pay and a CLEAR task to reset the
table before the next party sits.

`Runner` plays one person on the floor: one task at a time, the rest queue on the glasses (a RUN
card goes ahead of queued floor work). It reacts to the card after a short delay, accepts, keeps
the task open for a travel time (RUN) or a work time (ORDER, CHECK, CLEAR) and only then sends
`task.done`, which is what frees it for the next run (sim/README.md). A card that sits
unaccepted for 30 s because its server is busy escalates through the real TaskBook.

Both talk to a backend through a small interface (`Backend`), so the same world drives either the
real `Store` + `Hub` in-process (`run_offline`, here) or a running server over HTTP and WebSocket
(`live.py`). Offline, nothing sleeps: a heap of timed callbacks and the backend's own 1 s ticker
advance a fake clock that `Store` reads through its `clock` hook.
"""

from __future__ import annotations

import heapq
import itertools
import json
import os
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from scenario import COURSES, Party

Action = Callable[[], Awaitable[None]]
DESSERT_NOTE = "dessert order"
TICK_SEC = 1.0  # app/main.py tick_loop: min(TICK_SEC, escalation_sec / 4) with the defaults


class Scheduler(Protocol):
    def now(self) -> float: ...
    def at(self, t: float, fn: Action) -> None: ...


class Backend(Protocol):
    async def set_status(self, table: str, status: str) -> None: ...
    async def fire(self, table: str, lines: list[tuple[int, str]]) -> str: ...
    async def plate_up(self, order_id: str, line: int) -> None: ...
    async def create_task(self, kind: str, table: str, notes: list[str]) -> str: ...


# ---------- the floor staff ----------


@dataclass
class Runner:
    """One person's hands: one task at a time, cards queue while busy (RUN cards first)."""

    staff: str
    scn: dict[str, Any]
    sched: Scheduler
    send: Callable[[dict[str, Any]], Awaitable[None]]
    rng: random.Random
    queue: list[dict[str, Any]] = field(default_factory=list)
    current: str | None = None
    accepted: bool = False

    def on_message(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        task = msg.get("task") or {}
        if kind == "task.assigned" and task.get("assignee", self.staff) == self.staff:
            if task["id"] != self.current and all(q["id"] != task["id"] for q in self.queue):
                self.queue.append(task)
                self._next()
        elif kind == "task.updated" and task.get("state") == "bounced":
            # escalated away (unaccepted for 30 s) or rerouted (held past 5 min)
            self.queue = [q for q in self.queue if q["id"] != task["id"]]
            if task["id"] == self.current:
                self.current = None
                self._next()
        elif kind == "task.rejected" and msg.get("taskId") == self.current:
            self.current = None
            self._next()

    def reaction(self) -> float:
        r = self.scn["runner"]
        lo, hi = (
            r["slow_reaction_sec"]
            if self.rng.random() < r["slow_reaction_share"]
            else r["reaction_sec"]
        )
        return self.rng.uniform(lo, hi)

    def work(self, task: dict[str, Any]) -> float:
        """Seconds from accept to done: a trip to the table(s) and back, or the floor work."""
        r = self.scn["runner"]
        if task["kind"] == "RUN":
            extra = len(run_tables(task)) - 1
            return self.rng.uniform(*r["travel_sec"]) + r["per_extra_table_sec"] * extra
        return self.rng.uniform(*self.scn["floor_work_sec"][work_key(task)])

    def _next(self) -> None:
        if self.current is not None or not self.queue:
            return
        runs = [q for q in self.queue if q["kind"] == "RUN"]
        task = runs[0] if runs else self.queue[0]
        self.queue.remove(task)
        self.current, self.accepted = task["id"], False
        self.sched.at(self.sched.now() + self.reaction(), lambda: self._accept(task))

    async def _accept(self, task: dict[str, Any]) -> None:
        if self.current != task["id"]:
            return
        self.accepted = True
        await self.send({"type": "task.accept", "taskId": task["id"]})
        if self.current == task["id"]:
            self.sched.at(self.sched.now() + self.work(task), lambda: self._done(task))

    async def _done(self, task: dict[str, Any]) -> None:
        if self.current != task["id"]:
            return
        self.current = None
        await self.send({"type": "task.done", "taskId": task["id"]})
        self._next()


def work_key(task: dict[str, Any]) -> str:
    if task["kind"] == "ORDER" and DESSERT_NOTE in task.get("notes", []):
        return "DESSERT_ORDER"
    return str(task["kind"])


def run_tables(task: dict[str, Any]) -> list[str]:
    """The tables on a RUN card: its own, plus the 'also T5, T6' note for paired plates."""
    tables = [task["table"]]
    for note in task.get("notes", []):
        if note.startswith("also "):
            tables += [t.strip() for t in note.removeprefix("also ").split(",")]
    return tables


# ---------- guests and kitchen ----------


class World:
    def __init__(
        self,
        parties: list[Party],
        tables: list[dict[str, Any]],
        backend: Backend,
        sched: Scheduler,
    ) -> None:
        self.parties = parties
        self.tables = sorted(tables, key=lambda t: t["seats"])  # smallest table that fits
        self.free = {t["id"] for t in tables}
        self.backend = backend
        self.sched = sched
        self.waitlist: list[Party] = []
        self.left = 0
        self.cleared = 0
        self.plate_party: dict[str, tuple[Party, str]] = {}  # plate id -> (party, course)
        self.task_plates: dict[str, list[str]] = {}
        self.on_done: dict[str, Action] = {}  # floor task id -> what happens when it's done
        self.log: list[dict[str, Any]] = []  # sim.* records for the event stream

    @property
    def finished(self) -> bool:
        return self.cleared == len(self.parties)

    def note(self, type: str, **data: Any) -> None:
        self.log.append({"t": self.sched.now(), "type": type, "data": data})

    def start(self) -> None:
        for p in self.parties:
            self.sched.at(p.arrive_sec, lambda p=p: self.arrive(p))

    def after(self, sec: float, fn: Action) -> None:
        self.sched.at(self.sched.now() + sec, fn)

    async def task(self, kind: str, table: str, notes: list[str], then: Action) -> None:
        task_id = await self.backend.create_task(kind, table, notes)
        self.note("sim.task", taskId=task_id, kind=work_key({"kind": kind, "notes": notes}))
        self.on_done[task_id] = then

    async def arrive(self, p: Party) -> None:
        self.note("sim.arrive", party=p.id, size=p.size)
        self.waitlist.append(p)
        await self.seat_waiting()

    async def seat_waiting(self) -> None:
        for p in list(self.waitlist):
            table = next(
                (t["id"] for t in self.tables if t["id"] in self.free and t["seats"] >= p.size),
                None,
            )
            if table is None:
                continue
            self.waitlist.remove(p)
            self.free.discard(table)
            p.table = table
            self.note("sim.seat", party=p.id, table=table)
            await self.backend.set_status(table, "seated")
            self.after(p.sec["order_after_seated"], lambda p=p: self.ready_to_order(p))

    async def ready_to_order(self, p: Party) -> None:
        assert p.table is not None
        await self.task("ORDER", p.table, ["take order"], lambda: self.order(p))

    async def order(self, p: Party) -> None:
        """Appetizers and mains go in together; the kitchen times the mains off the appetizers."""
        lines = p.dishes["appetizer"] + p.dishes["main"]
        assert p.table is not None
        order_id = await self.backend.fire(p.table, lines)
        n_app = len(p.dishes["appetizer"])
        for i in range(len(lines)):
            course = "appetizer" if i < n_app else "main"
            self.plate_party[f"{order_id}:{i}"] = (p, course)
        p.order_ids = {"appetizer": order_id, "main": order_id}
        if n_app:
            self.cook(p, "appetizer", p.sec["appetizer_cook"], first_line=0)
        else:
            self.cook(p, "main", p.sec["mains_cook_no_appetizer"], first_line=0)

    def cook(self, p: Party, course: str, target_sec: float, first_line: int) -> None:
        order_id = p.order_ids[course]
        for k, jitter in enumerate(p.jitter[course]):
            line = first_line + k
            self.after(target_sec + jitter, lambda line=line: self.backend.plate_up(order_id, line))

    def on_backend_event(self, e: dict[str, Any]) -> None:
        """`pass.run` and `task.done` from the backend's log: food reached its table."""
        if e["type"] == "pass.run":
            self.task_plates[e["data"]["taskId"]] = list(e["data"]["plates"])
        elif e["type"] == "task.done":
            task_id = e["data"]["taskId"]
            for plate in self.task_plates.pop(task_id, []):
                self.delivered(plate)
            then = self.on_done.pop(task_id, None)
            if then is not None:
                self.sched.at(self.sched.now(), then)

    def delivered(self, plate: str) -> None:
        p, course = self.plate_party[plate]
        p.delivered.add(plate)
        order_id = p.order_ids[course]
        start = len(p.dishes["appetizer"]) if course == "main" else 0
        mine = {f"{order_id}:{start + k}" for k in range(len(p.dishes[course]))}
        if mine <= p.delivered:
            self.note("sim.course", party=p.id, table=p.table, course=course)
            self.sched.at(self.sched.now(), lambda: self.course_done(p, course))

    async def course_done(self, p: Party, course: str) -> None:
        assert p.table is not None
        await self.backend.set_status(p.table, "eating")
        if course == "appetizer":
            self.cook(p, "main", p.sec["mains_after_appetizers"], len(p.dishes["appetizer"]))
        elif course == "main" and p.dishes["dessert"]:
            self.after(p.sec["dessert_order_after_mains"], lambda: self.dessert_order(p))
        elif course == "main":
            self.after(p.sec["check_after_mains_no_dessert"], lambda: self.check(p))
        else:
            self.after(p.sec["check_after_dessert"], lambda: self.check(p))

    async def dessert_order(self, p: Party) -> None:
        assert p.table is not None
        await self.task("ORDER", p.table, [DESSERT_NOTE], lambda: self.dessert(p))

    async def dessert(self, p: Party) -> None:
        assert p.table is not None
        order_id = await self.backend.fire(p.table, p.dishes["dessert"])
        p.order_ids["dessert"] = order_id
        for i in range(len(p.dishes["dessert"])):
            self.plate_party[f"{order_id}:{i}"] = (p, "dessert")
        self.cook(p, "dessert", p.sec["dessert_cook"], first_line=0)

    async def check(self, p: Party) -> None:
        assert p.table is not None
        await self.backend.set_status(p.table, "check")
        await self.task("CHECK", p.table, [], lambda: self.leave(p))

    async def leave(self, p: Party) -> None:
        table = p.table
        assert table is not None
        await self.backend.set_status(table, "empty")
        self.note("sim.leave", party=p.id, table=table)
        self.left += 1
        await self.task("CLEAR", table, [], lambda: self.reset(p, table))

    async def reset(self, p: Party, table: str) -> None:
        self.note("sim.cleared", party=p.id, table=table)
        self.free.add(table)
        self.cleared += 1
        await self.seat_waiting()


assert COURSES == ("appetizer", "main", "dessert")


# ---------- offline: the real Store + Hub on a fake clock ----------


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class HeapScheduler:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.heap: list[tuple[float, int, Action]] = []
        self.seq = itertools.count()

    def now(self) -> float:
        return self.clock.t

    def at(self, t: float, fn: Action) -> None:
        heapq.heappush(self.heap, (max(t, self.clock.t), next(self.seq), fn))


class FakeSocket:
    """Stands in for a glasses WebSocket: the hub's sends go straight to a Runner."""

    def __init__(self, runner: Runner | None = None) -> None:
        self.runner = runner
        self.sent = 0

    async def send_text(self, text: str) -> None:
        self.sent += 1
        if self.runner is not None:
            self.runner.on_message(json.loads(text))


@dataclass
class OfflineResult:
    events: list[dict[str, Any]]
    world: World
    planner: str


async def run_offline(
    scn: dict[str, Any], parties: list[Party], planner: str, seed: int
) -> OfflineResult:
    from app import router
    from app.config import Settings
    from app.hub import Hub
    from app.runs import PLANNERS
    from app.state import Store

    os.environ.pop("GEMINI_API_KEY", None)  # routing on the rules only: no model calls
    clock = FakeClock()
    settings = Settings(gemini_api_key="", voice_relay_url="")
    store = Store.from_settings(settings, clock=clock)
    store.pass_.planner = planner  # type: ignore[assignment]
    store.events.append("pass.planner", planner=planner)
    hub = Hub(store, "")
    sched = HeapScheduler(clock)
    stream: list[dict[str, Any]] = []
    seen = 0

    class InProcess:
        async def set_status(self, table: str, status: str) -> None:
            store.set_table_status(table, status)
            await hub.push_floor()

        async def fire(self, table: str, lines: list[tuple[int, str]]) -> str:
            # the agent's add_item tool calls, then the server's tap (POST /orders/{id}/confirm)
            order_id = ""
            for seat, dish in lines:
                result, _ = store.orders.dispatch(
                    "add_item", {"table": table, "seat": seat, "dish": dish}
                )
                if "error" in result:
                    raise RuntimeError(f"add_item failed: {result}")
                order_id = result["orderId"]
            order = store.orders.fire(order_id)
            store.events.append("order.fired", orderId=order.id, table=order.table)
            await hub.after_fire(order)
            return order_id

        async def plate_up(self, order_id: str, line: int) -> None:
            store.plate_up(order_id, line)  # POST /pass/up
            await hub.replan(push=True)

        async def create_task(self, kind: str, table: str, notes: list[str]) -> str:
            # POST /tasks without an assignee: the router picks (rules, no Gemini key)
            who = await router.pick(store, hub.http, kind, table, notes)
            task, out = store.book.create(kind, table, store.now(), notes=notes, assignee=who)  # type: ignore[arg-type]
            await hub.deliver(out)
            return task.id

    world = World(parties, store.floor.to_dict()["tables"], InProcess(), sched)
    staff = [*store.floor.servers, store.floor.manager.id]
    sockets = {}
    for who in staff:
        ws = FakeSocket()

        async def send(frame: dict[str, Any], ws: FakeSocket = ws) -> None:
            await hub.on_text(ws, json.dumps(frame))  # type: ignore[arg-type]

        ws.runner = Runner(who, scn, sched, send, random.Random(f"{seed}:{who}"))
        sockets[who] = ws
        role = "manager" if who == store.floor.manager.id else "server"
        await hub.join(ws, role, who)  # type: ignore[arg-type]

    reserved: tuple[tuple[str, ...], tuple[str, ...]] = ((), ())

    def pump() -> None:
        """Stamp new backend events with the simulated time and let the world react."""
        nonlocal seen
        new = store.events.since(seen)
        seen += len(new)
        for ev in new:
            e = {"t": clock.t, "type": ev.type, "data": ev.data}
            stream.append(e)
            world.on_backend_event(e)
        stream.extend(world.log)
        world.log.clear()

    def observe() -> None:
        """Free servers held back because the best ready run needs more hands than are free.

        `free` is the pass's own view (no open RUN). `busy` marks the ones whose hands are full
        with accepted floor work (an order, a check), which the pass can't see.
        """
        nonlocal reserved
        free = store.free_runners()
        idle: tuple[str, ...] = ()
        busy: tuple[str, ...] = ()
        lead = None
        if free:
            p = store.pass_
            waiting = PLANNERS[p.planner](list(p.plates.values()), clock.t, p.weights, p._seq)
            if waiting:
                lead = waiting[0]
                idle = tuple(sorted(free))
                busy = tuple(
                    s for s in idle if any(t.state == "accepted" for t in store.book.open_for(s))
                )
        if (idle, busy) != reserved:
            reserved = (idle, busy)
            data: dict[str, Any] = {"idle": list(idle), "busy": list(busy)}
            if lead is not None:
                data |= {"runners": lead.runners, "plates": [x.id for x in lead.plates]}
            stream.append({"t": clock.t, "type": "sim.reserved", "data": data})

    async def tick() -> None:  # app/main.py tick_loop
        await hub.deliver(store.book.tick(store.now()))
        await hub.reroute_overdue()
        await hub.replan()

    world.start()
    pump()
    hard_stop = scn["hard_stop_min"] * 60
    next_tick = TICK_SEC
    while not world.finished and clock.t < hard_stop:
        if sched.heap and sched.heap[0][0] <= next_tick:
            t, _, fn = heapq.heappop(sched.heap)
            clock.t = t
            await fn()
        else:
            clock.t = next_tick
            next_tick += TICK_SEC
            await tick()
        pump()
        observe()
    if reserved[0]:
        stream.append({"t": clock.t, "type": "sim.reserved", "data": {"idle": [], "busy": []}})
    stream.append({"t": clock.t, "type": "sim.end", "data": {"finished": world.finished}})
    await hub.http.aclose()
    return OfflineResult(stream, world, planner)
