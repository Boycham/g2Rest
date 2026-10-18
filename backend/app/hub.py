"""WebSocket hub: who is connected as whom, delivery of Outbound messages, inbound gestures."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

from app.orders import ToolError
from app.state import Store
from app.tasks import Outbound, TaskError

log = logging.getLogger("fs.hub")
ROLES = ("server", "manager", "organizer")


@dataclass(frozen=True)
class Conn:
    ws: WebSocket
    role: str
    staff: str


class Hub:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.conns: dict[WebSocket, Conn] = {}
        self.last_capture: dict[WebSocket, str] = {}

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

    async def _send(self, conn: Conn, message: dict[str, Any]) -> bool:
        try:
            await conn.ws.send_text(json.dumps(message))
            return True
        except Exception as e:  # noqa: BLE001 - a dead socket must not stop delivery to others
            log.warning("[fs] send to %s failed: %r", conn.staff, e)
            self.leave(conn.ws)
            return False

    async def send_staff(self, staff: str, message: dict[str, Any]) -> int:
        delivered = 0
        for conn in list(self.conns.values()):
            if conn.staff == staff or conn.role == "organizer":
                ok = await self._send(conn, message)
                delivered += ok and conn.staff == staff
        return delivered

    async def broadcast(self, message: dict[str, Any], roles: tuple[str, ...] = ROLES) -> None:
        for conn in list(self.conns.values()):
            if conn.role in roles:
                await self._send(conn, message)

    async def deliver(self, outbound: list[Outbound]) -> None:
        for out in outbound:
            delivered = await self.send_staff(out.staff, out.message)
            if out.message["type"] == "task.assigned" and delivered:
                self.store.book.mark_sent(out.message["task"]["id"], self.store.now())

    async def push_floor(self) -> None:
        await self.broadcast(self.store.floor_state(), ("manager", "organizer"))

    # ---------- inbound ----------

    async def on_bytes(self, ws: WebSocket, data: bytes) -> None:
        cap_id = self.last_capture.get(ws)
        cap = self.store.captures.get(cap_id or "")
        if cap is None or not cap.open:
            log.warning("[fs] audio frame with no open capture (%d bytes)", len(data))
            return
        cap.frames += 1
        cap.bytes += len(data)

    async def on_text(self, ws: WebSocket, raw: str) -> None:
        conn = self.conns.get(ws)
        if conn is None:
            return
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("[fs] dropped non-JSON from %s: %.200s", conn.staff, raw)
            return
        if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
            log.warning("[fs] dropped shapeless message from %s", conn.staff)
            return
        self.store.events.append("ws.in", staff=conn.staff, message=msg)
        try:
            await self.handle(conn, msg)
        except (TaskError, ToolError, KeyError, TypeError) as e:
            log.warning("[fs] %s from %s rejected: %s", msg["type"], conn.staff, e)
            self.store.events.append(
                "ws.rejected", staff=conn.staff, type=msg["type"], error=str(e)
            )

    async def handle(self, conn: Conn, msg: dict[str, Any]) -> None:
        kind, now = msg["type"], self.store.now()
        book = self.store.book
        if kind == "task.accept":
            await self.deliver(book.accept(str(msg["taskId"]), now, by=conn.staff))
        elif kind == "task.done":
            await self.deliver(book.done(str(msg["taskId"]), now, by=conn.staff))
        elif kind == "task.bounce":
            await self.deliver(book.bounce(str(msg["taskId"]), now, by=conn.staff))
        elif kind == "capture.start":
            cap = self.store.start_capture(str(msg["captureId"]), conn.staff, msg.get("table"))
            self.last_capture[conn.ws] = cap.id
        elif kind == "capture.stop":
            self.store.stop_capture(str(msg["captureId"]))
        elif kind == "order.confirm":
            await self.close_order(conn, str(msg["orderId"]), fire=True)
        elif kind == "order.cancel_confirm":
            await self.close_order(conn, str(msg["orderId"]), fire=False)
        else:
            log.warning("[fs] unknown message type %r from %s", kind, conn.staff)

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
            self.store.set_table_status(order.table, "ordered")
            await self.push_floor()
        await self.send_staff(
            conn.staff, {"type": "order.closed", "orderId": order.id, "status": order.status}
        )

    async def push_order(self, table: str, message: dict[str, Any]) -> None:
        owner = self.store.capture_owner(table)
        if owner:
            await self.send_staff(owner, message)
