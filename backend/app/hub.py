"""WebSocket hub: who is connected as whom, delivery of Outbound messages, inbound gestures."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import WebSocket

from app import router, telemetry
from app.contract import ContractError, check_backend, parse_glasses
from app.orders import ToolError
from app.state import Store
from app.tasks import Outbound, TaskError
from app.voice_bridge import VoiceBridge

log = logging.getLogger("fs.hub")
ROLES = ("server", "manager", "organizer")
DEFAULT_STAFF = {"organizer": "organizer"}  # never a server: organizers only watch
AUDIO_LOG_EVERY = 10  # one log line per second of 100 ms frames


@dataclass(frozen=True)
class Conn:
    ws: WebSocket
    role: str
    staff: str


class Hub:
    def __init__(
        self,
        store: Store,
        voice_relay_url: str = "",
        http: httpx.AsyncClient | None = None,
        *,
        trace_wire: bool = False,
    ) -> None:
        self.store = store
        self.trace_wire = trace_wire  # send `trace` on task.assigned (CONTRACT.md §8.12)
        self.http = http or httpx.AsyncClient()  # the router's Gemini calls
        self.conns: dict[WebSocket, Conn] = {}
        self.last_capture: dict[WebSocket, str] = {}
        self.command_capture: dict[WebSocket, str] = {}
        self.voice = (
            VoiceBridge(
                voice_relay_url,
                store,
                self.after_fire,
                after_draft=self.after_voice_draft,
                after_cancel=self.after_cancel,
                after_close=self.finish_order_task,
            )
            if voice_relay_url
            else None
        )

    # ---------- connections ----------

    async def join(self, ws: WebSocket, role: str, staff: str) -> Conn:
        conn = Conn(ws, role, staff)
        self.conns[ws] = conn
        self.store.events.append("ws.open", role=role, staff=staff)
        log.info("[fs] ws open role=%s staff=%s (%d total)", role, staff, len(self.conns))
        await self.send_current_state(conn)
        return conn

    def leave(self, ws: WebSocket) -> None:
        conn = self.conns.pop(ws, None)
        self.last_capture.pop(ws, None)
        self.command_capture.pop(ws, None)
        if self.voice:
            self.voice.drop(ws)
        if conn:
            self.store.events.append("ws.close", role=conn.role, staff=conn.staff)
            log.info("[fs] ws close staff=%s (%d left)", conn.staff, len(self.conns))

    async def send_current_state(self, conn: Conn) -> None:
        """Current state, not a replay: open tasks for this staff member, the floor, open alerts."""
        now = self.store.now()
        for task in self.store.book.open_for(conn.staff):
            await self._send(conn, {"type": "task.assigned", "task": task.wire()})
            self.store.book.mark_sent(task.id, now)
        if conn.role in ("manager", "organizer"):
            await self._send(conn, self.store.floor_state())
            for alert in self.store.book.alerts.values():
                await self._send(conn, alert.wire())

    # ---------- outbound ----------

    async def _send(self, conn: Conn, message: dict[str, Any], check: bool = True) -> bool:
        try:
            if check:
                check_backend(message)
        except ContractError as e:
            log.error(
                "[fs] not sending off-contract %s to %s: %s", message.get("type"), conn.staff, e
            )
            return False
        if self.trace_wire and message.get("type") == "task.assigned":
            message = self._with_trace(message)
        try:
            await conn.ws.send_text(json.dumps(message))
            return True
        except Exception as e:  # noqa: BLE001 - a dead socket must not stop delivery to others
            log.warning("[fs] send to %s failed: %r", conn.staff, e)
            self.leave(conn.ws)
            return False

    def _with_trace(self, message: dict[str, Any]) -> dict[str, Any]:
        task = self.store.book.tasks.get(message["task"]["id"])
        trace = telemetry.current_trace() or (task.trace if task else None)
        return {**message, "trace": trace} if trace else message

    async def send_staff(self, staff: str, message: dict[str, Any]) -> int:
        delivered = 0
        for conn in list(self.conns.values()):
            if conn.staff == staff or conn.role == "organizer":
                ok = await self._send(conn, message)
                delivered += ok and conn.staff == staff and conn.role != "organizer"
        return delivered

    async def broadcast(self, message: dict[str, Any], roles: tuple[str, ...] = ROLES) -> None:
        for conn in list(self.conns.values()):
            if conn.role in roles:
                await self._send(conn, message)

    async def deliver(self, outbound: list[Outbound]) -> None:
        for out in outbound:
            kind = out.message["type"]
            with telemetry.span("hub.deliver", f"{kind} -> {out.staff}", staff=out.staff):
                delivered = await self.send_staff(out.staff, out.message)
            if out.message["type"] == "task.assigned" and delivered:
                self.store.book.mark_sent(out.message["task"]["id"], self.store.now())

    async def push_floor(self) -> None:
        await self.broadcast(self.store.floor_state(), ("manager", "organizer"))

    async def to_organizers(self, message: dict[str, Any]) -> None:
        """Web-page-only messages (pass.state, order.fired): not part of the glasses contract."""
        for conn in list(self.conns.values()):
            if conn.role == "organizer":
                await self._send(conn, message, check=False)

    async def push_pass(self) -> None:
        await self.to_organizers(self.store.pass_.state(self.store.now()))

    async def after_fire(self, order: Any) -> None:
        self.store.on_fired(order)
        await self.push_floor()
        await self.to_organizers({"type": "order.fired", "order": order.to_dict()})
        await self.push_pass()

    async def after_cancel(self, order: Any) -> None:
        await self.to_organizers({"type": "order.cancelled", "order": order.to_dict()})

    async def after_voice_draft(self, order: Any) -> None:
        """A voice draft as it builds: the organizer and kitchen pages show it forming."""
        await self.to_organizers({"type": "order.draft", **order.to_dict()})

    async def finish_order_task(self, staff: str, table: str | None, status: str) -> None:
        """The order was sent or cancelled: the server's ORDER task for that table is done."""
        now = self.store.now()
        for task in self.store.book.open_for(staff):
            if task.kind == "ORDER" and task.table == table:
                await self.deliver(self.store.book.done(task.id, now, by=staff))
                self.store.events.append("order.task_done", taskId=task.id, status=status)

    async def reroute_overdue(self) -> None:
        """Accepted tasks held past `done_sec`: alert the manager and let the router move them."""
        book = self.store.book
        for task in book.overdue(self.store.now()):
            to = await router.pick(
                self.store,
                self.http,
                task.kind,
                task.table,
                task.notes,
                exclude=frozenset({task.assignee}),
            )
            out = book.reroute(task.id, self.store.now(), to)
            if out:
                await self.deliver(out)
                await self.replan()

    async def replan(self, *, push: bool = False) -> bool:
        """Hand out any run a free server can take now; push pass.state if something moved."""
        out = self.store.dispatch()
        if out:
            with telemetry.root("pass.run", "run dispatch", tasks=len(out)):
                await self.deliver(out)
        if out or push:
            await self.push_pass()
        return bool(out)

    # ---------- inbound ----------

    async def on_bytes(self, ws: WebSocket, data: bytes) -> None:
        cap = self.store.captures.get(self.last_capture.get(ws) or "")
        if cap is None or not cap.open:
            cap = self.store.captures.get(self.command_capture.get(ws) or "")
        if cap is None or not cap.open:
            log.warning("[fs] audio frame with no open capture (%d bytes)", len(data))
            return
        cap.frames += 1
        cap.bytes += len(data)
        if self.voice:
            await self.voice.audio(ws, data)
        if cap.frames % AUDIO_LOG_EVERY == 0:
            log.info("[fs] audio frames: %d", cap.frames)

    async def on_text(self, ws: WebSocket, raw: str) -> None:
        conn = self.conns.get(ws)
        if conn is None:
            return
        try:
            msg = parse_glasses(raw)
        except ContractError as e:
            log.warning("[fs] off-contract frame from %s dropped: %s", conn.staff, e)
            self.store.events.append("ws.rejected", staff=conn.staff, error=str(e))
            return
        self.store.events.append("ws.in", staff=conn.staff, message=msg.model_dump())
        try:
            with telemetry.root(msg.type, self._frame_name(conn, msg), self._trace_for(msg)):
                await self.handle(conn, msg)
        except (TaskError, ToolError) as e:
            log.warning("[fs] %s from %s rejected: %s", msg.type, conn.staff, e)
            self.store.events.append("ws.rejected", staff=conn.staff, frame=msg.type, error=str(e))
            if msg.type.startswith("task."):
                rejected = {
                    "type": "task.rejected",
                    "taskId": getattr(msg, "taskId", None),
                    "action": msg.type.removeprefix("task."),
                    "reason": str(e),
                }
                await self._send(conn, rejected)

    def _trace_for(self, msg: Any) -> telemetry.Trace | None:
        """The frame's own trace (glasses Sentry, proposed), else the task's: the accept or
        done then joins the trace of the organizer click or food up that made the task."""
        if getattr(msg, "trace", None) is not None:
            return msg.trace.model_dump(exclude_none=True)
        task = self.store.book.tasks.get(getattr(msg, "taskId", None) or "")
        return task.trace if task else None

    def _frame_name(self, conn: Conn, msg: Any) -> str:
        task = self.store.book.tasks.get(getattr(msg, "taskId", None) or "")
        return f"{msg.type} {task.kind} {task.table}" if task else f"{msg.type} {conn.staff}"

    async def handle(self, conn: Conn, msg: Any) -> None:
        now = self.store.now()
        book = self.store.book
        match msg.type:
            case "task.accept":
                await self.deliver(book.accept(msg.taskId, now, by=conn.staff))
            case "task.done":
                await self.deliver(book.done(msg.taskId, now, by=conn.staff))
                await self.replan()
            case "task.bounce":
                await self.deliver(book.bounce(msg.taskId, now, by=conn.staff))
                await self.replan()
            case "task.handoff":
                task = book.get(msg.taskId)
                to = msg.to or await router.pick(
                    self.store,
                    self.http,
                    task.kind,
                    task.table,
                    task.notes,
                    exclude=frozenset({conn.staff}),
                )
                await self.deliver(book.handoff(msg.taskId, self.store.now(), conn.staff, to))
                await self.replan()
            case "task.revert":
                await self.deliver(book.revert(now, conn.staff, msg.taskId))
                await self.replan()
            case "capture.start":
                command = msg.mode == "command"
                cap = self.store.start_capture(
                    msg.captureId, conn.staff, msg.table, bind=not command
                )
                (self.command_capture if command else self.last_capture)[conn.ws] = cap.id
                await self.to_voice(conn, msg, table=cap.table)
            case "capture.stop":
                cap = self.store.stop_capture(msg.captureId)
                if cap is not None:
                    log.info("[fs] audio frames: %d (capture %s closed)", cap.frames, cap.id)
                await self.to_voice(conn, msg)
            case "order.confirm" | "order.cancel_confirm" | "order.reject" if (
                self.voice and self.voice.owns(conn.ws, msg.orderId)
            ):
                await self.to_voice(conn, msg)
            case "order.confirm":
                await self.close_order(conn, msg.orderId, fire=True)
            case "order.cancel_confirm":
                await self.close_order(conn, msg.orderId, fire=False)

    async def to_voice(self, conn: Conn, msg: Any, table: str | None = None) -> None:
        if self.voice:
            send = lambda m: self._send(conn, m)  # noqa: E731
            body = msg.model_dump(exclude_none=True)
            if table:
                body["table"] = table
            await self.voice.text(conn.ws, conn.staff, send, body)

    async def close_order(self, conn: Conn, order_id: str, *, fire: bool) -> None:
        order = self.store.orders.fire(order_id) if fire else self.store.orders.cancel(order_id)
        self.store.events.append(
            "order." + order.status,
            orderId=order.id,
            table=order.table,
            staff=conn.staff,
            lines=[ln.wire() for ln in order.lines],
        )
        if fire:
            await self.after_fire(order)
        else:
            await self.after_cancel(order)
        await self.send_staff(
            conn.staff, {"type": "order.closed", "orderId": order.id, "status": order.status}
        )

    async def push_order(self, table: str, message: dict[str, Any]) -> None:
        owner = self.store.capture_owner(table)
        if owner:
            await self.send_staff(owner, message)
