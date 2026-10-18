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
from pathlib import Path
from typing import Any, Protocol

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from commands import Command, parse_commands, tables_said
from gemini_intent import IntentUnavailable, map_words
from order import UNKNOWN_TABLE, Menu, OrderBook, ToolError, floor_tables
from voice_session import (
    FRAME_BYTES,
    AgentSession,
    ScribeStream,
    log,
    speech_end_offset,
    transcribe_clip,
)

PORT = int(os.environ.get("VOICE_RELAY_PORT", "8790"))
START_TIMEOUT = 8.0  # Scribe + agent connect, each already has its own timeout
MAX_BUFFERED_FRAMES = 50  # 5 s of audio kept while the providers connect
MAX_CLIP_FRAMES = 1220  # a 120 s clip plus slack; anything past it is dropped
Transcribe = Callable[[bytes], Awaitable[list[tuple[str, str]]]]


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


def table_number(label: str | None) -> int | None:
    """'T3' / '3' -> 3; anything else -> None."""
    raw = (label or "").strip().upper().removeprefix("T")
    return int(raw) if raw.isdigit() and 1 <= int(raw) <= 999 else None


def clip_message(turns: list[tuple[str, str]], book: OrderBook) -> str:
    t = book.current_table
    whence = {
        "task": "from the ORDER task",
        "voice": "set by the server",
        "spoken": "said in a clip",
    }
    where = (
        f"table {t} ({whence[book.table_source]})" if t and book.table_source else "not known yet"
    )
    lines = "\n".join(f"{speaker}: {text}" for speaker, text in turns)
    return f"CLIP, last 2 minutes at the table, oldest first. Table: {where}.\n{lines}"


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
        return f"CANCEL T{p['table'] or '?'} {', '.join(names)}?"
    return f"SEND T{p['table'] or '?'} to kitchen?"


def build_draft(
    book: OrderBook, order_id: str, capture_id: str, voice: str, notice: str | None
) -> dict[str, Any]:
    """order.draft for the table being ordered. Fields past `allergies` are PROPOSED."""
    t = book.draft_table
    table = book.tables.get(t)
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
        "table": f"T{t}" if t != UNKNOWN_TABLE else None,
        "lines": lines,
        "allergies": [{"allergen": k, "seats": v} for k, v in allergies.items()],
        "status": table.status if table else "draft",
        "pending": pending,
        "voice": voice,
        "notice": notice,
        "notes": list(table.notes) if table else [],
        "uncertain": list(table.uncertain) if table else [],
        "summary": table.summary if table else "",
        "answers": [
            {
                **({"seat": a["seat"]} if a.get("seat") else {}),
                "q": a["q"],
                "a": a["a"],
                "known": a["answered"],
            }
            for a in (table.answers if table else [])
        ],
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
        transcribe: Transcribe | None = None,
        make_talk_agent: Callable[[OrderBook, Callable[..., None]], Agent | None] | None = None,
    ):
        self._send = send
        self.make_stt = make_stt
        self.make_agent = make_agent
        self.book = OrderBook(Menu.load(), floor_tables())
        self.order_id = uuid.uuid4().hex[:8]
        self.capture_id = ""
        self.voice = "idle"  # PROPOSED: idle | connecting | listening | offline
        self.notice: str | None = None
        self.stt: Stt | None = None
        self.agent: Agent | None = None
        # The clip's second agent (set_talk: summary and answers), run beside the order agent
        # so the order card never waits for it. None: no talk agent configured.
        self.make_talk_agent = make_talk_agent
        self.talk_agent: Agent | None = None
        self.buffer: list[bytes] = []
        self.segments: asyncio.Queue[str] = asyncio.Queue()
        self.tasks: set[asyncio.Task[None]] = set()
        self.speech_end = 0.0
        self.transcribe = transcribe or transcribe_clip
        self.mode = "stream"
        self.clip = bytearray()
        self.clip_stop = 0.0
        self.got_order = False
        self.agent_ready: asyncio.Task[None] | None = None
        self.cmd_stt: Stt | None = None
        self.cmd_capture_id = ""
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
        if tool == "set_talk":
            if not is_error and self.clip_stop:
                log(f"latency clip stop -> set_talk {time.monotonic() - self.clip_stop:.2f}s")
            self._spawn(self.draft())
            return
        if tool == "set_order" and not is_error:
            self.got_order = True
            self.voice = "idle"
            self.notice = result.get("table_notice")
            if self.clip_stop:
                log(f"latency clip stop -> set_order {time.monotonic() - self.clip_stop:.2f}s")
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

    def _bind(self, table: str | None) -> None:
        n = table_number(table)
        if n is None or self.book.table_source == "voice":
            return
        try:
            self.book.bind_table(n, "task")
        except ToolError as e:
            self.notice = str(e)[:60]

    async def capture_start(
        self, capture_id: str, table: str | None = None, mode: str | None = None
    ) -> None:
        if mode == "command":
            await self._command_start(capture_id)
            return
        current = self.book.tables.get(self.book.draft_table)
        if current and current.status != "draft":
            self.book = OrderBook(Menu.load(), floor_tables())
            self.order_id = uuid.uuid4().hex[:8]
            if self.agent:
                await self.agent.close()
                self.agent = None
        await self._close_stt()
        if mode == "clip":
            await self._clip_start(capture_id, table)
            return
        self.mode = "stream"
        self._bind(table)
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

    # ---- commands: "verity <command>" on the always-on stream ----

    async def _command_start(self, capture_id: str) -> None:
        """Live Scribe on the command stream. Only matched intents leave this method; the
        transcript itself is never logged, stored or sent."""
        if self.cmd_stt:
            await self.cmd_stt.close()

        def committed(text: str, t: float) -> None:
            for cmd in parse_commands(text):
                self._spawn(self._command(cmd))

        stt = self.make_stt(lambda text: None, committed)
        self.cmd_stt, self.cmd_capture_id = stt, capture_id
        try:
            await asyncio.wait_for(stt.open(), START_TIMEOUT)
        except (Exception, SystemExit) as e:  # noqa: BLE001 - commands are optional
            log(f"command stream offline: {type(e).__name__}: {e}")
            if self.cmd_stt is stt:
                self.cmd_stt = None

    async def _command(self, cmd: Command) -> None:
        """A fixed-list intent goes straight out; other words after "verity" go to Gemini,
        and anything it can't map shows as `Didn't get: <words>` on the card."""
        intent, name = cmd.intent, cmd.name
        if intent == "table":
            await self._table_command(cmd.table)
            return
        if intent == "unknown":
            words = cmd.words or ""
            await self._send({"type": "voice.mapping", "words": words})
            try:
                mapped = await map_words(words)
            except IntentUnavailable as e:
                log(f"voice command unmapped ({e})")
                await self._send({"type": "voice.unknown", "words": words, "reason": str(e)})
                return
            if mapped is None:
                log("voice command unmapped")
                await self._send({"type": "voice.unknown", "words": words})
                return
            intent, name = mapped
            log(f"voice command {intent} (gemini)")
        else:
            log(f"voice command {intent}")
        msg: dict[str, Any] = {"type": "voice.command", "intent": intent}
        if name:
            msg["name"] = name
        await self._send(msg)

    async def _table_command(self, n: int | None) -> None:
        """ "verity table N": bind the unsent draft to table N, over an ORDER task's table."""
        msg: dict[str, Any] = {"type": "voice.command", "intent": "table"}
        was = self.book.current_table
        if n is None:
            msg["reason"] = "say verity table and a number"
        elif not self.book.tables and was is None:
            msg["table"], msg["reason"] = f"T{n}", "no order to set the table for"
        else:
            msg["table"] = f"T{n}"
            try:
                self.book.bind_table(n, "voice")
            except ToolError as e:
                msg["reason"] = str(e)[:60]
            else:
                if was is not None and was != n:
                    msg["was"] = f"T{was}"
                self.notice = None
                await self.draft()
        log(f"voice command table {msg.get('table', '?')} {msg.get('reason', 'ok')}")
        await self._send(msg)

    async def _command_frame(self, frame: bytes) -> None:
        stt = self.cmd_stt
        if not stt or not stt.alive:
            return
        try:
            await stt.send(frame)
        except (Exception, SystemExit) as e:  # noqa: BLE001 - commands are optional
            log(f"command stream send failed: {type(e).__name__}: {e}")
            self.cmd_stt = None

    # ---- clip: the last 2 minutes from the glasses' rolling buffer ----

    async def _clip_start(self, capture_id: str, table: str | None) -> None:
        self.mode = "clip"
        self.capture_id = capture_id
        self.clip = bytearray()
        self.notice = None
        self.voice = "processing"
        self._bind(table)
        await self.draft()
        if not self.agent or not self.agent.alive:
            self.agent_ready = self._spawn(self._start_agent())

    async def _start_agent(self) -> None:
        self.agent = self.make_agent(self.book, self.on_tool)
        await asyncio.wait_for(self.agent.start(), START_TIMEOUT)

    async def _talk(self, capture_id: str, message: str) -> None:
        """The summary and answers for a clip; any failure only means no talk lines."""
        if not self.make_talk_agent or capture_id != self.capture_id:
            return
        try:
            if not self.talk_agent or not self.talk_agent.alive:
                self.talk_agent = self.make_talk_agent(self.book, self.on_tool)
                if not self.talk_agent:
                    return
                await asyncio.wait_for(self.talk_agent.start(), START_TIMEOUT)
            await self.talk_agent.say(message)
        except (Exception, SystemExit) as e:  # noqa: BLE001 - the order card is unaffected
            log(f"talk agent: {type(e).__name__}: {e}")
            self.talk_agent = None

    def _bind_said(self, heard: str) -> None:
        """The last floor table said anywhere in the clip ("that was table four", even as
        its last words), unless the ORDER task or "verity table" already set one."""
        said = [n for n in tables_said(heard) if self.book.floor is None or n in self.book.floor]
        if said and self.book.table_source in (None, "spoken"):
            try:
                self.book.bind_table(said[-1], "spoken")
            except ToolError as e:
                self.notice = str(e)[:60]

    async def _process_clip(self, capture_id: str, pcm: bytes) -> None:
        self.clip_stop = time.monotonic()
        try:
            turns = await self.transcribe(pcm)
            log(f"clip {len(pcm) / 32000:.1f}s -> {len(turns)} turns in "
                f"{time.monotonic() - self.clip_stop:.2f}s")  # fmt: skip
            if self.agent_ready:
                await self.agent_ready
            if not self.agent or not self.agent.alive:
                await self._start_agent()
        except (Exception, SystemExit) as e:  # noqa: BLE001 - shown on the glasses
            if capture_id == self.capture_id:
                await self._offline(f"clip: {type(e).__name__}: {e}")
            return
        if capture_id != self.capture_id:
            return
        if not turns:
            self.voice, self.notice = "idle", "heard nothing in the last 2 min"
            await self.draft()
            return
        self.got_order = False
        assert self.agent
        heard = " ".join(text for _, text in turns)
        self.book.hear(heard)
        self._bind_said(heard)
        message = clip_message(turns, self.book)
        self._spawn(self._talk(capture_id, message))
        try:
            await self.agent.say(message)
        except (Exception, SystemExit) as e:  # noqa: BLE001 - shown on the glasses
            await self._offline(f"agent: {type(e).__name__}: {e}")
            return
        if not self.got_order and capture_id == self.capture_id:
            self.voice, self.notice = "idle", "no order heard in the last 2 min"
            await self.draft()

    async def audio(self, frame: bytes) -> None:
        clip_upload = self.mode == "clip" and self.voice == "processing"
        if self.cmd_stt and not clip_upload:
            await self._command_frame(frame)
            return
        if self.mode == "clip":
            room = len(self.clip) < MAX_CLIP_FRAMES * FRAME_BYTES
            if len(frame) == FRAME_BYTES and self.voice == "processing" and room:
                self.clip += frame
            return
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
        if capture_id == self.cmd_capture_id and self.cmd_stt:
            stt, self.cmd_stt = self.cmd_stt, None
            await stt.close()
            return
        if capture_id != self.capture_id:
            return
        if self.mode == "clip":
            pcm, self.clip = bytes(self.clip), bytearray()  # in memory only, then dropped
            self._spawn(self._process_clip(capture_id, pcm))
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
                t = self.book.draft_table
                if t == UNKNOWN_TABLE:
                    raise ToolError("say the table first (TABLE?)")
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
            table = msg.get("table") if isinstance(msg.get("table"), str) else None
            mode = msg.get("mode") if msg.get("mode") in ("stream", "clip", "command") else None
            await self.capture_start(msg["captureId"], table, mode)
        elif kind == "capture.stop" and isinstance(msg.get("captureId"), str):
            await self.capture_stop(msg["captureId"])
        elif kind in ("order.confirm", "order.cancel_confirm", "order.reject"):
            await self.gesture(msg)
        else:
            log(f"ignored {raw[:200]}")

    async def close(self) -> None:
        await self._close_stt()
        if self.cmd_stt:
            await self.cmd_stt.close()
        if self.agent:
            await self.agent.close()
        if self.talk_agent:
            await self.talk_agent.close()
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


def live_talk_agent(book: OrderBook, on_tool: Callable[..., None]) -> Agent | None:
    aid = os.environ.get("ELEVENLABS_TALK_AGENT_ID")
    saved = Path(__file__).with_name(".talk_agent_id")
    if not aid and saved.exists():
        aid = saved.read_text().strip()
    if not aid:
        return None
    return AgentSession(aid, book, on_tool, lambda text: log(f"talk agent: {text}"))


async def handler(ws: ServerConnection) -> None:
    log(f"glasses connected via {ws.request.path if ws.request else '?'}")

    async def send(msg: dict[str, Any]) -> None:
        try:
            await asyncio.wait_for(ws.send(json.dumps(msg)), 2.0)
        except (ConnectionClosed, TimeoutError):
            pass

    session = RelaySession(send, live_stt, live_agent, make_talk_agent=live_talk_agent)
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
