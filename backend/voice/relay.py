"""Voice relay: the capture.* / order.* half of the glasses contract, over one WebSocket.

    python relay.py            (ws://localhost:8790/ws, VOICE_RELAY_PORT to change)

Glasses (via the fake backend's proxy) send capture.start, binary capture.audio frames
(16 kHz s16le mono, 3200 bytes), capture.stop, and order.confirm / order.cancel_confirm /
order.reject for the server's taps and swipes. The relay streams the audio to Scribe,
hands each committed segment to the text-only agent, runs its tool calls on the
OrderBook and answers with order.draft after every change. The ElevenLabs key stays here.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from order import Menu, OrderBook, ToolError
from voice_session import FRAME_BYTES, AgentSession, ScribeStream, log, speech_end_offset

PORT = int(os.environ.get("VOICE_RELAY_PORT", "8790"))
START_TIMEOUT = 8.0  # Scribe + agent connect, each already has its own timeout
MAX_BUFFERED_FRAMES = 50  # 5 s of audio kept while the providers connect


class Stt(Protocol):
    @property
    def alive(self) -> bool: ...
    async def open(self) -> None: ...
    async def send(self, frame: bytes, commit: bool = False) -> None: ...
    async def finish(self) -> None: ...
    async def close(self) -> None: ...


class Agent(Protocol):
    @property
    def alive(self) -> bool: ...
    async def start(self) -> None: ...
    async def say(self, text: str) -> None: ...
    async def contextual_update(self, text: str) -> None: ...
    async def close(self) -> None: ...


def dish_label(book: OrderBook, name: str) -> str:
    """Short glanceable name: the first menu alias ("halibut"), else the full name."""
    dish = book.menu.dishes.get(name)
    return dish.aliases[0] if dish and dish.aliases else name.lower()


def proposal_text(book: OrderBook, p: dict[str, Any]) -> str:
    if p["action"] == "remove":
        return f"REMOVE s{p['seat']} {dish_label(book, p['dish'])}?"
    if p["action"] == "cancel":
        names = [
            "order"
            if i == "whole order"
            else i.removeprefix("course:")
            if i.startswith("course:")
            else dish_label(book, i)
            for i in p["items"]
        ]
        return f"CANCEL T{p['table']} {', '.join(names)}?"
    return f"SEND T{p['table']} to kitchen?"


def build_draft(
    book: OrderBook, order_id: str, capture_id: str, voice: str, notice: str | None
) -> dict[str, Any]:
    """order.draft for the table being ordered. Fields past `allergies` are PROPOSED."""
    t = book.current_table
    table = book.tables.get(t) if t is not None else None
    lines: list[dict[str, Any]] = []
    allergies: dict[str, list[int]] = {}
    pending: list[dict[str, str]] = []
    if table:
        for n, seat in sorted(table.seats.items()):
            for item in seat.items:
                lines.append(
                    {
                        "seat": n,
                        "qty": item.qty,
                        "dish": dish_label(book, item.dish),
                        "alterations": list(item.alterations),
                        "flagged": list(item.flagged_alterations),
                    }
                )
            for a in seat.allergies:
                allergies.setdefault(a.upper(), []).append(n)
        for p in table.proposals:
            action = {"fire": "confirm"}.get(p["action"], p["action"])
            pending.append({"id": p["id"], "action": action, "text": proposal_text(book, p)})
    return {
        "type": "order.draft",
        "orderId": order_id,
        "captureId": capture_id,
        "table": f"T{t}" if t is not None else None,
        "lines": lines,
        "allergies": [{"allergen": k, "seats": v} for k, v in allergies.items()],
        "status": table.status if table else "draft",
        "pending": pending,
        "voice": voice,
        "notice": notice,
    }


def tool_notice(book: OrderBook, tool: str, params: dict[str, Any], result: dict[str, Any]) -> str:
    """The glasses line for a rejected tool call, written by code rather than the agent."""
    if tool == "remove_item" and "has no" in result.get("error", ""):
        try:
            label = dish_label(book, book.menu.resolve(str(params.get("dish"))).name)
        except ToolError:
            label = str(params.get("dish"))
        return f"s{params.get('seat')} has no {label}: nothing removed"
    return "? " + result.get("error", "tool error").split(";")[0].split(". ")[0][:60]


class RelaySession:
    """One glasses connection. `send` writes a JSON message back to the glasses."""

    def __init__(
        self,
        send: Callable[[dict[str, Any]], Awaitable[None]],
        make_stt: Callable[[Callable[[str], None], Callable[[str, float], None]], Stt],
        make_agent: Callable[[OrderBook, Callable[..., None]], Agent],
    ):
        self._send = send
        self.make_stt = make_stt
        self.make_agent = make_agent
        self.book = OrderBook(Menu.load())
        self.order_id = uuid.uuid4().hex[:8]
        self.capture_id = ""
        self.voice = "idle"  # PROPOSED: idle | connecting | listening | offline
        self.notice: str | None = None
        self.stt: Stt | None = None
        self.agent: Agent | None = None
        self.buffer: list[bytes] = []
        self.segments: asyncio.Queue[str] = asyncio.Queue()
        self.tasks: set[asyncio.Task[None]] = set()
        self.speech_end = 0.0
        self.worker = self._spawn(self._forward_segments())

    def _spawn(self, coro: Awaitable[None]) -> asyncio.Task[None]:
        task: asyncio.Task[None] = asyncio.ensure_future(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def draft(self) -> None:
        msg = build_draft(self.book, self.order_id, self.capture_id, self.voice, self.notice)
        if self.speech_end and self.voice != "listening":
            log(f"latency speech end -> order.draft sent {time.monotonic() - self.speech_end:.2f}s")
            self.speech_end = 0.0
        await self._send(msg)

    # ---- agent ----

    def on_tool(
        self, tool: str, params: dict[str, Any], result: dict[str, Any], is_error: bool, t: float
    ) -> None:
        log(f"tool {tool}({json.dumps(params)}) -> {'ERROR' if is_error else 'ok'}")
        self.notice = tool_notice(self.book, tool, params, result) if is_error else None
        self._spawn(self.draft())

    async def _forward_segments(self) -> None:
        while True:
            text = await self.segments.get()
            if not self.agent or not self.agent.alive:
                await self._offline("agent not connected")
                continue
            try:
                await self.agent.say(text)
            except (Exception, SystemExit) as e:  # noqa: BLE001 - shown on the glasses
                await self._offline(f"agent: {type(e).__name__}: {e}")

    async def _offline(self, why: str) -> None:
        log(f"VOICE OFFLINE: {why}")
        self.voice = "offline"
        await self.draft()

    # ---- capture ----

    async def capture_start(self, capture_id: str) -> None:
        table = self.book.tables.get(self.book.current_table or -1)
        if table and table.status != "draft":
            self.book = OrderBook(Menu.load())
            self.order_id = uuid.uuid4().hex[:8]
            if self.agent:
                await self.agent.close()
                self.agent = None
        await self._close_stt()
        self.capture_id = capture_id
        self.voice = "connecting"
        self.notice = None
        self.buffer = []
        await self.draft()

        def committed(text: str, t: float) -> None:
            log(f"committed: {text}")
            self.segments.put_nowait(text)

        stt = self.make_stt(lambda text: log(f"partial: {text}"), committed)
        self.stt = stt
        try:
            if not self.agent or not self.agent.alive:
                self.agent = self.make_agent(self.book, self.on_tool)
                await asyncio.wait_for(
                    asyncio.gather(stt.open(), self.agent.start()), START_TIMEOUT
                )
            else:
                await asyncio.wait_for(stt.open(), START_TIMEOUT)
        except (Exception, SystemExit) as e:  # noqa: BLE001 - shown on the glasses
            if self.stt is stt:
                await self._close_stt()
                await self._offline(f"start: {type(e).__name__}: {e}")
            return
        if self.stt is not stt or self.capture_id != capture_id:
            await stt.close()
            return
        self.voice = "listening"
        for frame in self.buffer:
            await self._send_frame(frame)
        self.buffer = []
        await self.draft()

    async def audio(self, frame: bytes) -> None:
        if len(frame) != FRAME_BYTES or self.voice not in ("connecting", "listening"):
            log(f"dropped audio frame ({len(frame)} bytes, voice {self.voice})")
            return
        if speech_end_offset(frame) > 0:
            self.speech_end = time.monotonic()
        if self.voice == "connecting":
            if len(self.buffer) < MAX_BUFFERED_FRAMES:
                self.buffer.append(frame)
            return
        await self._send_frame(frame)

    async def _send_frame(self, frame: bytes) -> None:
        if not self.stt or not self.stt.alive:
            await self._close_stt()
            await self._offline("speech-to-text socket closed")
            return
        try:
            await self.stt.send(frame)
        except (Exception, SystemExit) as e:  # noqa: BLE001 - shown on the glasses
            await self._close_stt()
            await self._offline(f"stt send: {type(e).__name__}: {e}")

    async def capture_stop(self, capture_id: str) -> None:
        if capture_id != self.capture_id:
            return
        stt, self.stt = self.stt, None
        if self.voice != "offline":
            self.voice = "idle"
        await self.draft()
        if stt:
            self._spawn(stt.finish())

    async def _close_stt(self) -> None:
        stt, self.stt = self.stt, None
        if stt:
            await stt.close()

    # ---- the server's taps and swipes ----

    async def gesture(self, msg: dict[str, Any]) -> None:
        if msg.get("orderId") != self.order_id:
            log(f"{msg['type']} for stale order {msg.get('orderId')}; resending draft")
            await self.draft()
            return
        proposal_id = msg.get("proposalId")
        try:
            if msg["type"] == "order.reject":
                result = self.book.reject(str(proposal_id))
                update = f"The server rejected: {json.dumps(result)}. Do not retry it."
            elif proposal_id:
                result = self.book.accept(str(proposal_id))
                update = f"The server tapped to apply: {json.dumps(result)}."
            elif msg["type"] == "order.cancel_confirm":
                t = self.book.current_table
                if t is None:
                    raise ToolError("no table yet")
                self.book.tables[t].proposals.clear()
                proposal = self.book.dispatch("cancel_order", {"table": t})[0]
                result = self.book.accept(proposal["id"])
                update = f"The server tapped to cancel the whole order: {json.dumps(result)}."
            else:
                t = self.book.current_table
                if t is None:
                    raise ToolError("no table yet")
                self.book.fire(t)
                result = {"status": "sent", "table": t}
                update = f"The server tapped to send table {t}'s order to the kitchen."
            self.notice = None
            log(f"{msg['type']} {proposal_id or ''} -> {result['status']}")
        except ToolError as e:
            self.notice = str(e)[:60]
            update = ""
        await self.draft()
        if update and self.agent and self.agent.alive:
            try:
                await self.agent.contextual_update(update)
            except (Exception, SystemExit) as e:  # noqa: BLE001 - the draft is already right
                log(f"contextual update failed: {e}")

    async def handle_text(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            log(f"invalid JSON {raw[:200]}")
            return
        kind = msg.get("type") if isinstance(msg, dict) else None
        if kind == "capture.start" and isinstance(msg.get("captureId"), str):
            await self.capture_start(msg["captureId"])
        elif kind == "capture.stop" and isinstance(msg.get("captureId"), str):
            await self.capture_stop(msg["captureId"])
        elif kind in ("order.confirm", "order.cancel_confirm", "order.reject"):
            await self.gesture(msg)
        else:
            log(f"ignored {raw[:200]}")

    async def close(self) -> None:
        await self._close_stt()
        if self.agent:
            await self.agent.close()
        for task in list(self.tasks):
            task.cancel()


def agent_id() -> str:
    from run_spike import agent_id as saved_agent_id

    return saved_agent_id()


def live_stt(on_partial: Callable[[str], None], on_committed: Callable[[str, float], None]) -> Stt:
    return ScribeStream(on_partial, on_committed)


def live_agent(book: OrderBook, on_tool: Callable[..., None]) -> Agent:
    try:
        aid = agent_id()
    except SystemExit as e:
        raise ConnectionError(str(e)) from None
    return AgentSession(aid, book, on_tool, lambda text: log(f"agent: {text}"))


async def handler(ws: ServerConnection) -> None:
    log(f"glasses connected via {ws.request.path if ws.request else '?'}")

    async def send(msg: dict[str, Any]) -> None:
        try:
            await asyncio.wait_for(ws.send(json.dumps(msg)), 2.0)
        except (ConnectionClosed, TimeoutError):
            pass

    session = RelaySession(send, live_stt, live_agent)
    try:
        async for data in ws:
            if isinstance(data, bytes):
                await session.audio(data)
            else:
                await session.handle_text(data)
    except ConnectionClosed:
        pass
    finally:
        await session.close()
        log("glasses disconnected")


async def main() -> None:
    async with serve(handler, "localhost", PORT, max_size=2**20) as server:
        log(f"voice relay on ws://localhost:{PORT}/ws")
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
