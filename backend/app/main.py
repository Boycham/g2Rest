"""Floor Sense backend: FastAPI app, HTTP API and the /ws hub (CONTRACT.md).

FS_TOKEN=dev .venv/bin/uvicorn app.main:app --port 8787 --reload
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import Settings
from app.data import DataError
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


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = store or Store.from_settings(settings)
    hub = Hub(store)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        ticker = asyncio.create_task(tick_loop())
        log.info("[fs] backend up, token %s", "set" if settings.token else "EMPTY (dev)")
        yield
        ticker.cancel()

    async def tick_loop() -> None:
        while True:
            await asyncio.sleep(min(TICK_SEC, settings.escalation_sec / 4))
            try:
                await hub.deliver(store.book.tick(store.now()))
                await hub.replan()
            except Exception:  # noqa: BLE001 - the ticker must survive any one bad task
                log.exception("[fs] tick failed")

    app = FastAPI(title="Floor Sense backend", lifespan=lifespan)
    app.state.store, app.state.hub = store, hub
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
        return {"ok": True, "tasksOpen": len(store.book.open_tasks()), "clients": len(hub.conns)}

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
            task, out = store.book.create(
                body.kind,
                store.floor.table(body.table).id,
                store.now(),
                items=body.items,
                allergies=body.allergies,
                notes=body.notes,
                assignee=body.assignee,
                priority=body.priority,
            )
        except DataError as e:
            raise HTTPException(404, str(e)) from None
        await hub.deliver(out)
        return task.to_dict()

    @app.get("/tasks", dependencies=auth)
    def list_tasks() -> list[dict[str, Any]]:
        return [t.to_dict() for t in store.book.tasks.values()]

    @app.post("/tasks/{task_id}/{action}", dependencies=auth)
    async def task_action(task_id: str, action: str) -> dict[str, Any]:
        moves = {"accept": store.book.accept, "done": store.book.done, "bounce": store.book.bounce}
        if action not in moves:
            raise HTTPException(404, f"action must be one of {sorted(moves)}")
        try:
            out = moves[action](task_id, store.now())
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
