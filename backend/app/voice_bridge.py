"""Voice bridge: the hub's capture.* / order.* traffic to backend/voice/relay.py and back.

The glasses keep one socket, to the hub. The first `capture.start` on a glasses socket dials the
relay (VOICE_RELAY_URL); JSON and binary frames go through as they are, and every relay
`order.draft` comes back to that socket. When the relay reports an order `sent` (the server's
final tap), its lines go into the hub's own order store through the same tools as POST /tools/*,
the order is fired (organizer, kitchen pass) and the glasses get `order.closed`. The ElevenLabs
key lives only in the relay's environment.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from app.orders import Order, ToolError
from app.state import Store

log = logging.getLogger("fs.voice")
CONNECT_TIMEOUT_SEC = 3.0
SEND_TIMEOUT_SEC = 2.0
QUEUE_MAX = 50
OFFLINE_NOTICE = "voice relay unreachable"

Send = Callable[[dict[str, Any]], Awaitable[Any]]
OrderHook = Callable[[Order], Awaitable[None]]
CloseHook = Callable[[str, str | None, str], Awaitable[None]]
NO_TABLE = "TABLE?"  # label of a live voice draft whose table is not known yet


async def _no_order_hook(order: Order) -> None:
    return None


async def _no_close_hook(staff: str, table: str | None, status: str) -> None:
    return None


@dataclass
class Link:
    """One glasses socket's connection to the relay."""

    send: Send
    staff: str
    relay: ClientConnection | None = None
    dialing: asyncio.Task[None] | None = None
    reader: asyncio.Task[None] | None = None
    queue: list[str | bytes] = field(default_factory=list)
    capture_id: str = ""
    last_draft: dict[str, Any] | None = None
    orders: set[str] = field(default_factory=set)
    closed: set[str] = field(default_factory=set)
    dropped: bool = False


class VoiceBridge:
    def __init__(
        self,
        url: str,
        store: Store,
        after_fire: OrderHook,
        dial: Callable[..., Any] = connect,
        *,
        after_draft: OrderHook = _no_order_hook,
        after_cancel: OrderHook = _no_order_hook,
        after_close: CloseHook = _no_close_hook,
    ) -> None:
        self.url = url
        self.store = store
        self.after_fire = after_fire
        self.after_draft = after_draft
        self.after_cancel = after_cancel
        self.after_close = after_close
        self.dial = dial
        self.links: dict[Any, Link] = {}

    def owns(self, ws: Any, order_id: str) -> bool:
        """True if this order id came from the relay on this socket (not a hub draft)."""
        link = self.links.get(ws)
        return link is not None and order_id in link.orders

    async def text(self, ws: Any, staff: str, send: Send, message: dict[str, Any]) -> None:
        link = self.links.get(ws)
        if link is None:
            link = self.links[ws] = Link(send, staff)
            await self._forward(link, json.dumps(self._menu_86(self.store.eighty_six)))
        if message.get("type") == "capture.start" and message.get("mode") != "command":
            link.capture_id = str(message.get("captureId", ""))
        await self._forward(link, json.dumps(message))

    @staticmethod
    def _menu_86(dishes: list[str]) -> dict[str, Any]:
        return {"type": "menu.86", "dishes": dishes}

    async def menu_86(self, dishes: list[str]) -> None:
        """Tell every relay session what is 86'd; its set_order turns those into `?` lines."""
        for link in list(self.links.values()):
            await self._forward(link, json.dumps(self._menu_86(dishes)))

    async def audio(self, ws: Any, data: bytes) -> None:
        link = self.links.get(ws)
        if link is not None:
            await self._forward(link, data)

    def drop(self, ws: Any) -> None:
        link = self.links.pop(ws, None)
        if link is None:
            return
        link.dropped = True
        for task in (link.dialing, link.reader):
            if task:
                task.cancel()
        if link.relay:
            asyncio.get_running_loop().create_task(link.relay.close())

    # ---------- to the relay ----------

    async def _forward(self, link: Link, data: str | bytes) -> None:
        if link.relay is not None:
            try:
                await asyncio.wait_for(link.relay.send(data), SEND_TIMEOUT_SEC)
                return
            except (ConnectionClosed, TimeoutError) as e:
                log.warning("[fs] voice relay send failed: %r", e)
                link.relay = None
        if isinstance(data, str) or len(link.queue) < QUEUE_MAX:
            link.queue.append(data)
        if link.dialing is None or link.dialing.done():
            link.dialing = asyncio.get_running_loop().create_task(self._dial(link))

    async def _dial(self, link: Link) -> None:
        try:
            relay = await asyncio.wait_for(self.dial(self.url, max_size=2**20), CONNECT_TIMEOUT_SEC)
        except (OSError, TimeoutError, WebSocketException) as e:
            log.warning("[fs] voice relay %s unreachable: %r", self.url, e)
            link.queue.clear()
            await self._offline(link)
            return
        log.info("[fs] voice relay connected %s for %s", self.url, link.staff)
        link.relay = relay
        queued, link.queue = link.queue, []
        try:
            for data in queued:
                await asyncio.wait_for(relay.send(data), SEND_TIMEOUT_SEC)
        except (ConnectionClosed, TimeoutError) as e:
            log.warning("[fs] voice relay flush failed: %r", e)
        link.reader = asyncio.get_running_loop().create_task(self._read(link, relay))

    # ---------- from the relay ----------

    async def _read(self, link: Link, relay: ClientConnection) -> None:
        try:
            async for raw in relay:
                if isinstance(raw, str):
                    await self._from_relay(link, raw)
        except ConnectionClosed:
            pass
        finally:
            if link.relay is relay:
                link.relay = None
            if not link.dropped:
                log.warning("[fs] voice relay closed for %s", link.staff)
                await self._offline(link)

    async def _from_relay(self, link: Link, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("[fs] relay sent invalid JSON %s", raw[:200])
            return
        if not isinstance(msg, dict) or msg.get("type") != "order.draft":
            await link.send(msg)
            return
        order_id = str(msg.get("orderId", ""))
        if order_id:
            link.orders.add(order_id)
            link.last_draft = msg
        await link.send(msg)
        status = msg.get("status")
        if order_id and status in (None, "draft") and (msg.get("lines") or msg.get("allergies")):
            await self._live_draft(link, msg)
        if order_id and status in ("sent", "cancelled") and order_id not in link.closed:
            link.closed.add(order_id)
            await self._close(link, msg)

    async def _live_draft(self, link: Link, draft: dict[str, Any]) -> None:
        """Mirror the relay's draft into the hub's store so the kitchen sees it forming."""
        try:
            order = self.build_order(draft, link.staff, live=True)
        except ToolError as e:
            log.warning("[fs] live draft %s not mirrored: %s", draft.get("orderId"), e)
            return
        self.store.orders.orders[order.id] = order
        await self.after_draft(order)

    async def _close(self, link: Link, draft: dict[str, Any]) -> None:
        relay_id = draft["orderId"]
        if draft["status"] == "cancelled":
            self.store.events.append("order.cancelled", orderId=relay_id, staff=link.staff)
            live = self.store.orders.get(f"order-{relay_id}")
            if live is not None and live.status == "draft":
                await self.after_cancel(self.store.orders.cancel(live.id))
            await link.send({"type": "order.closed", "orderId": relay_id, "status": "cancelled"})
            await self.after_close(link.staff, draft.get("table"), "cancelled")
            return
        try:
            order = self.fire_into_store(draft, link.staff)
        except ToolError as e:
            log.error("[fs] voice order %s not fired: %s", relay_id, e)
            await link.send({**draft, "status": "draft", "notice": f"not sent: {e}"[:60]})
            link.closed.discard(relay_id)
            return
        self.store.events.append(
            "order.fired",
            orderId=order.id,
            relayOrderId=relay_id,
            table=order.table,
            staff=link.staff,
            lines=[ln.wire() for ln in order.lines],
        )
        log.info("[fs] voice order %s fired as %s (%s)", relay_id, order.id, order.summary())
        await self.after_fire(order)
        await link.send({"type": "order.closed", "orderId": relay_id, "status": "fired"})
        await self.after_close(link.staff, order.table, "fired")

    def fire_into_store(self, draft: dict[str, Any], staff: str) -> Order:
        """The relay's final draft -> a fired order in the hub's store, through the order tools."""
        order = self.build_order(draft, staff)
        if not order.lines:
            raise ToolError("the order is empty")
        self.store.orders.orders[order.id] = order
        return self.store.orders.fire(order.id)

    def build_order(self, draft: dict[str, Any], staff: str, *, live: bool = False) -> Order:
        """A relay draft -> a draft Order (full menu names), through the same tools as
        POST /tools/*. `live`: a draft still being taken may have no table yet."""
        orders = self.store.orders
        table = draft.get("table")
        if table not in orders.tables:
            if not (live and table is None):
                raise ToolError(f"unknown table {table!r}")
            table = NO_TABLE
        order = Order(
            id=f"order-{draft['orderId']}",
            table=table,
            capture_id=draft.get("captureId") or None,
            owner=staff,
        )
        for line in draft.get("lines", []):
            orders.tool_add_item(
                order,
                {
                    "seat": line["seat"],
                    "dish": line["dish"],
                    "qty": line["qty"],
                    "alterations": [*line.get("alterations", []), *line.get("flagged", [])],
                },
            )
        for allergy in draft.get("allergies", []):
            for seat in allergy["seats"]:
                orders.tool_set_allergy(order, {"seat": seat, "allergen": allergy["allergen"]})
        return order

    async def _offline(self, link: Link) -> None:
        base = link.last_draft or {
            "type": "order.draft",
            "orderId": "",
            "captureId": link.capture_id,
            "table": None,
            "lines": [],
            "allergies": [],
        }
        await link.send({**base, "voice": "offline", "notice": OFFLINE_NOTICE})
