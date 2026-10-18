"""Floor Sense backend: FastAPI app, HTTP API and the /ws hub (CONTRACT.md).

FS_TOKEN=dev .venv/bin/uvicorn app.main:app --port 8787 --reload
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import router, telemetry
from app.config import Settings
from app.data import DataError
from app.eventdb import EventDB, asyncpg_connect
from app.hub import DEFAULT_STAFF, ROLES, Hub
from app.orders import TOOL_NAMES, ToolError
from app.runs import PassError
from app.state import Store
from app.tasks import TaskError, TaskKind

log = logging.getLogger("fs")
TICK_SEC = 1.0


class TaskIn(BaseModel):
    kind: TaskKind
    table: str
    items: list[dict[str, Any]] = Field(default_factory=list)
    allergies: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    assignee: str | None = None
    priority: float = 0.0


class StatusIn(BaseModel):
    status: str


class PlateUp(BaseModel):
    orderId: str
    line: int = Field(ge=0)


class PlannerIn(BaseModel):
    planner: Literal["priority", "fifo"]


def create_app(
    settings: Settings | None = None, store: Store | None = None, eventdb: EventDB | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    sentry_on = telemetry.init_sentry(
        settings.sentry_dsn_backend, settings.sentry_environment, settings.sentry_traces_rate
    )
    store = store or Store.from_settings(settings)
    if eventdb is None and settings.database_url:
        eventdb = EventDB(asyncpg_connect(settings.database_url))
    if eventdb is not None:
        for event in store.events.since(0):
            eventdb.offer(event)
        store.events.listeners.append(eventdb.offer)
    http = httpx.AsyncClient()
    hub = Hub(store, settings.voice_relay_url, http, trace_wire=settings.trace_wire)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        ticker = asyncio.create_task(tick_loop())
        writer = asyncio.create_task(eventdb.run()) if eventdb else None
        log.info(
            "[fs] backend up, token %s, event db %s, Sentry %s",
            "set" if settings.token else "EMPTY (dev)",
            "on" if eventdb else "off",
            "on" if sentry_on else "off",
        )
        yield
        ticker.cancel()
        if writer and eventdb:
            writer.cancel()
            await eventdb.close()
        await http.aclose()

    async def tick_loop() -> None:
        while True:
            await asyncio.sleep(min(TICK_SEC, settings.escalation_sec / 4))
            try:
                if out := store.book.tick(store.now()):
                    with telemetry.root("task.escalate", "escalate", messages=len(out)):
                        await hub.deliver(out)
                await hub.reroute_overdue()
                await hub.replan()
            except Exception:  # noqa: BLE001 - the ticker must survive any one bad task
                log.exception("[fs] tick failed")

    app = FastAPI(title="Floor Sense backend", lifespan=lifespan)
    app.state.store, app.state.hub, app.state.eventdb = store, hub, eventdb
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def token_ok(token: str | None) -> bool:
        return not settings.token or token == settings.token

    def require_token(request: Request) -> None:
        header = request.headers.get("authorization", "")
        bearer = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else None
        if not token_ok(bearer or request.query_params.get("token")):
            raise HTTPException(401, "bad or missing token")

    auth = [Depends(require_token)]

    # ---------- open ----------

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "tasksOpen": len(store.book.open_tasks()),
            "clients": len(hub.conns),
            "eventDb": eventdb.status() if eventdb else {"enabled": False},
            "sentry": sentry_on,
        }

    @app.get("/config", dependencies=auth)
    def config() -> dict[str, Any]:
        """What the web pages need at load: the browser Sentry DSN (none committed in web/)."""
        if not settings.sentry_dsn_web:
            return {"sentry": None}
        return {
            "sentry": {
                "dsn": settings.sentry_dsn_web,
                "environment": settings.sentry_environment,
                "tracesSampleRate": settings.sentry_traces_rate,
            }
        }

    # ---------- websocket ----------

    @app.websocket("/ws")
    async def ws_endpoint(
        ws: WebSocket,
        token: str | None = Query(default=None),
        role: str = Query(default="server"),
        staff: str | None = Query(default=None),
    ) -> None:
        await ws.accept()
        if not token_ok(token):
            await ws.close(code=4401, reason="bad token")
            return
        if role not in ROLES:
            await ws.close(code=4400, reason=f"role must be one of {ROLES}")
            return
        if staff is None:
            staff = DEFAULT_STAFF.get(role) or next(iter(store.floor.servers))
            if role == "manager":
                staff = store.floor.manager.id
        await hub.join(ws, role, staff)
        try:
            while True:
                frame = await ws.receive()
                if frame.get("type") == "websocket.disconnect":
                    break
                if frame.get("bytes") is not None:
                    await hub.on_bytes(ws, frame["bytes"])
                elif frame.get("text") is not None:
                    await hub.on_text(ws, frame["text"])
        except WebSocketDisconnect:
            pass
        finally:
            hub.leave(ws)

    # ---------- state ----------

    @app.get("/state", dependencies=auth)
    def state() -> dict[str, Any]:
        return store.snapshot()

    @app.get("/events", dependencies=auth)
    def events(since: int = 0) -> list[dict[str, Any]]:
        return [e.to_dict() for e in store.events.since(since)]

    @app.get("/menu", dependencies=auth)
    def menu() -> dict[str, Any]:
        return store.menu.to_dict()

    @app.get("/floor", dependencies=auth)
    def floor() -> dict[str, Any]:
        return store.floor.to_dict()

    @app.post("/reset", dependencies=auth)
    async def reset() -> dict[str, Any]:
        store.reset()
        await hub.push_floor()
        return {"ok": True}

    # ---------- tasks ----------

    @app.post("/tasks", dependencies=auth, status_code=201)
    async def create_task(body: TaskIn) -> dict[str, Any]:
        try:
            table = store.floor.table(body.table).id
        except DataError as e:
            raise HTTPException(404, str(e)) from None
        with telemetry.span("task.dispatch", f"dispatch {body.kind} {table}", kind=body.kind):
            assignee = body.assignee or await router.pick(store, http, body.kind, table, body.notes)
            try:
                task, out = store.book.create(
                    body.kind,
                    table,
                    store.now(),
                    items=body.items,
                    allergies=body.allergies,
                    notes=body.notes,
                    assignee=assignee,
                    priority=body.priority,
                )
            except DataError as e:
                raise HTTPException(404, str(e)) from None
            await hub.deliver(out)
        return task.to_dict()

    @app.get("/stats", dependencies=auth)
    async def stats(hours: float = Query(default=24.0, gt=0, le=24 * 30)) -> dict[str, Any]:
        """How long each server takes: for the manager dashboard (and the router's context).
        `history`: accept latency and ticket time per server and kind over the last `hours`,
        from the Tiger Data continuous aggregates (every boot, not just this service)."""
        history = (
            await eventdb.stats(hours)
            if eventdb
            else {"available": False, "reason": "DATABASE_URL not set"}
        )
        return {
            "doneSec": settings.done_sec,
            "servers": store.book.stats(store.now()),
            "history": history,
        }

    @app.get("/tasks", dependencies=auth)
    def list_tasks() -> list[dict[str, Any]]:
        return [t.to_dict() for t in store.book.tasks.values()]

    @app.post("/tasks/{task_id}/{action}", dependencies=auth)
    async def task_action(task_id: str, action: str, by: str = Query(...)) -> dict[str, Any]:
        """The assignee's own gesture over HTTP (simulator, tests). `by` must be the assignee:
        only the server holding a task accepts, finishes or bounces it, never the organizer."""
        moves = {"accept": store.book.accept, "done": store.book.done, "bounce": store.book.bounce}
        if action not in moves:
            raise HTTPException(404, f"action must be one of {sorted(moves)}")
        with telemetry.span(f"task.{action}", f"task.{action} {task_id}", by=by):
            try:
                out = moves[action](task_id, store.now(), by=by)
            except TaskError as e:
                raise HTTPException(409, str(e)) from None
            await hub.deliver(out)
            await hub.replan()
        return store.book.get(task_id).to_dict()

    # ---------- tables ----------

    @app.post("/tables/{table_id}/status", dependencies=auth)
    async def table_status(table_id: str, body: StatusIn) -> dict[str, Any]:
        try:
            store.set_table_status(table_id, body.status)
        except DataError as e:
            raise HTTPException(400, str(e)) from None
        await hub.push_floor()
        return store.table_wire(table_id)

    # ---------- agent tools ----------

    @app.post("/tools/{tool}", dependencies=auth)
    async def tool(tool: str, request: Request) -> dict[str, Any]:
        if tool not in TOOL_NAMES:
            raise HTTPException(404, f"tool must be one of {TOOL_NAMES}")
        try:
            params = await request.json()
        except ValueError:
            params = None
        result, order = store.orders.dispatch(tool, params)
        store.events.append("tool." + tool, params=params, result=result)
        if order is not None:
            await hub.push_order(order.table, order.draft_wire())
            if result.get("status") == "needs_confirmation":
                readback = {
                    "type": "order.readback",
                    "orderId": order.id,
                    "action": result["action"],
                    "text": result["readback"],
                }
                await hub.push_order(order.table, readback)
        return result

    @app.post("/orders/{order_id}/{action}", dependencies=auth)
    async def order_action(order_id: str, action: str) -> dict[str, Any]:
        """Organizer stand-in for the glasses tap: confirm or cancel a draft."""
        if action not in ("confirm", "cancel"):
            raise HTTPException(404, "action must be confirm or cancel")
        order = store.orders.get(order_id)
        if order is None:
            raise HTTPException(404, f"unknown order {order_id}")
        try:
            fire = action == "confirm"
            order = store.orders.fire(order_id) if fire else store.orders.cancel(order_id)
        except ToolError as e:
            raise HTTPException(409, str(e)) from None
        store.events.append("order." + order.status, orderId=order.id, table=order.table)
        if fire:
            await hub.after_fire(order)
        else:
            await hub.after_cancel(order)
        await hub.push_order(
            order.table, {"type": "order.closed", "orderId": order.id, "status": order.status}
        )
        return order.to_dict()

    # ---------- the pass (kitchen page) ----------

    @app.get("/pass", dependencies=auth)
    async def pass_state() -> dict[str, Any]:
        return store.pass_.state(store.now())

    @app.post("/pass/up", dependencies=auth)
    async def plate_up(body: PlateUp) -> dict[str, Any]:
        """Food up: mark the plate, give the best ready run to a free server, return the pass."""
        with telemetry.span("pass.up", f"food up {body.orderId}:{body.line}"):
            try:
                store.plate_up(body.orderId, body.line)
            except PassError as e:
                raise HTTPException(409, str(e)) from None
            await hub.replan(push=True)
        return store.pass_.state(store.now())

    @app.post("/pass/planner", dependencies=auth)
    async def set_planner(body: PlannerIn) -> dict[str, Any]:
        """Simulator switch: 'priority' (default) or 'fifo' for the baseline."""
        store.pass_.planner = body.planner
        store.events.append("pass.planner", planner=body.planner)
        await hub.push_pass()
        return {"planner": body.planner, "weights": store.pass_.weights.to_dict()}

    return app


app = create_app()
