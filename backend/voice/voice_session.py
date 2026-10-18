"""ElevenLabs session: Scribe realtime STT in, text-only agent with client tools out.

Message shapes follow the docs recorded in NOTES.md. The API key stays here on the
backend; nothing in this module logs it.
"""

from __future__ import annotations

import array
import asyncio
import base64
import json
import math
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from order import OrderBook

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

API = "https://api.elevenlabs.io"
WSS = "wss://api.elevenlabs.io"
STT_MODEL = "scribe_v2_realtime"
BATCH_STT_MODEL = "scribe_v2"
# Pinned: a real-G2 test transcribed bystanders and once switched the stream to Turkish.
STT_LANGUAGE = "en"
CLIP_STT_TIMEOUT = 20.0
SAMPLE_RATE = 16000
FRAME_BYTES = 3200  # 100 ms of 16 kHz s16le mono, same as a G2 mic frame
FRAME_SECS = 0.1
HTTP_TIMEOUT = 10.0
STT_ERRORS = {
    "error", "auth_error", "quota_exceeded", "transcriber_error", "input_error",
    "invalid_request", "commit_throttled", "unaccepted_terms", "rate_limited",
    "queue_overflow", "resource_exhausted", "session_time_limit_exceeded",
    "chunk_size_exceeded", "insufficient_audio_activity",
}  # fmt: skip

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "add_item",
        "description": "Add a dish for one seat. Use the exact menu name.",
        "parameters": {
            "type": "object",
            "required": ["table", "seat", "dish", "qty"],
            "properties": {
                "table": {"type": "integer", "description": "Table number"},
                "seat": {"type": "integer", "description": "Seat number at the table"},
                "dish": {"type": "string", "description": "Exact dish name from the menu"},
                "qty": {"type": "integer", "description": "How many, usually 1"},
                "alterations": {
                    "type": "array",
                    "description": "Requested changes, e.g. 'no butter'. Empty if none.",
                    "items": {"type": "string", "description": "One alteration"},
                },
            },
        },
    },
    {
        "name": "remove_item",
        "description": "PROPOSE removing a dish the server named from one seat. It must be "
        "on that seat. It is not removed until the server taps on the glasses.",
        "parameters": {
            "type": "object",
            "required": ["table", "seat", "dish"],
            "properties": {
                "table": {"type": "integer", "description": "Table number"},
                "seat": {"type": "integer", "description": "Seat number at the table"},
                "dish": {"type": "string", "description": "Exact dish name from the menu"},
            },
        },
    },
    {
        "name": "modify_item",
        "description": "Add one alteration to a dish already ordered for a seat.",
        "parameters": {
            "type": "object",
            "required": ["table", "seat", "dish", "change"],
            "properties": {
                "table": {"type": "integer", "description": "Table number"},
                "seat": {"type": "integer", "description": "Seat number at the table"},
                "dish": {"type": "string", "description": "Exact dish name from the menu"},
                "change": {"type": "string", "description": "The alteration, e.g. 'no dill'"},
            },
        },
    },
    {
        "name": "set_allergy",
        "description": "Pin an allergy to a seat.",
        "parameters": {
            "type": "object",
            "required": ["table", "seat", "allergen"],
            "properties": {
                "table": {"type": "integer", "description": "Table number"},
                "seat": {"type": "integer", "description": "Seat number at the table"},
                "allergen": {"type": "string", "description": "The allergen, e.g. 'shellfish'"},
            },
        },
    },
    {
        "name": "confirm_order",
        "description": "PROPOSE sending the table's order to the kitchen. It is not sent until "
        "the server taps on the glasses.",
        "parameters": {
            "type": "object",
            "required": ["table"],
            "properties": {"table": {"type": "integer", "description": "Table number"}},
        },
    },
    {
        "name": "cancel_order",
        "description": "PROPOSE cancelling a table's order, or only some items or a course. "
        "Nothing is cancelled until the server taps on the glasses.",
        "parameters": {
            "type": "object",
            "required": ["table"],
            "properties": {
                "table": {"type": "integer", "description": "Table number"},
                "items": {
                    "type": "array",
                    "description": "Dish names or a course (appetizer, main, dessert). "
                    "Omit to cancel the whole order.",
                    "items": {"type": "string", "description": "Dish name or course"},
                },
            },
        },
    },
]


_ITEM = {
    "type": "object",
    "description": "One dish for one guest",
    "required": ["guest", "dish"],
    "properties": {
        "guest": {
            "type": "integer",
            "description": "1 for the first guest to order, 2 for the next, and so on",
        },
        "seat": {
            "type": "integer",
            "description": "Only if a seat number is said aloud for this dish; else omit",
        },
        "dish": {"type": "string", "description": "Exact dish name from the menu"},
        "qty": {"type": "integer", "description": "How many, usually 1"},
        "alterations": {
            "type": "array",
            "description": "Requested changes, e.g. 'no butter'. Empty if none.",
            "items": {"type": "string", "description": "One alteration"},
        },
    },
}
CLIP_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "set_order",
        "description": "Set the complete order heard in the clip for this table. Call it once "
        "per clip. It never sends or cancels anything; the server taps on the glasses.",
        "parameters": {
            "type": "object",
            "required": ["items"],
            "properties": {
                "table": {
                    "type": "integer",
                    "description": "Only if a table number is said for this order; else omit",
                },
                "items": {"type": "array", "description": "Every dish ordered", "items": _ITEM},
                "allergies": {
                    "type": "array",
                    "description": "Allergies a guest states",
                    "items": {
                        "type": "object",
                        "description": "One allergy",
                        "required": ["guest", "allergen"],
                        "properties": {
                            "guest": {"type": "integer", "description": "Guest number"},
                            "seat": {"type": "integer", "description": "Only if said aloud"},
                            "allergen": {"type": "string", "description": "e.g. 'shellfish'"},
                        },
                    },
                },
                "unclear": {
                    "type": "array",
                    "description": "Anything ambiguous, as a short statement, never a question",
                    "items": {
                        "type": "object",
                        "description": "One unclear point",
                        "required": ["text"],
                        "properties": {
                            "guest": {"type": "integer", "description": "Guest number, if any"},
                            "text": {
                                "type": "string",
                                "description": "e.g. \"'the fish': halibut or salmon\"",
                            },
                        },
                    },
                },
                "notes": {
                    "type": "array",
                    "description": "Occasion, pacing or timing worth knowing, a few words each",
                    "items": {"type": "string", "description": "e.g. 'anniversary'"},
                },
            },
        },
    }
]


def log(msg: str) -> None:
    print(f"[fs] {msg}", flush=True)


def api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise SystemExit("[fs] ELEVENLABS_API_KEY is not set")
    if not key.startswith("sk_"):
        raise SystemExit("[fs] ELEVENLABS_API_KEY does not start with sk_ (is it the key ID?)")
    return key


def speech_end_offset(pcm: bytes, threshold_dbfs: float = -40.0) -> float:
    """Seconds from the start of the clip to the end of the last voiced 100 ms frame."""
    pcm = pcm[: len(pcm) // 2 * 2]
    last = 0
    for i in range(0, len(pcm), FRAME_BYTES):
        samples = array.array("h", pcm[i : i + FRAME_BYTES])
        rms = math.sqrt(sum(x * x for x in samples) / len(samples)) or 1e-9
        if 20 * math.log10(rms / 32768) > threshold_dbfs:
            last = i // FRAME_BYTES + 1
    return last * FRAME_SECS


class ScribeStream:
    """One Scribe realtime socket fed 100 ms PCM frames as they arrive (mic or file)."""

    def __init__(
        self,
        on_partial: Callable[[str], None],
        on_committed: Callable[[str, float], None],
        *,
        vad_silence_secs: float = 0.8,
        open_timeout: float = 5.0,
        send_timeout: float = 2.0,
    ):
        self.on_partial = on_partial
        self.on_committed = on_committed
        self.vad_silence_secs = vad_silence_secs
        self.open_timeout = open_timeout
        self.send_timeout = send_timeout
        self.ws: ClientConnection | None = None
        self._reader: asyncio.Task[None] | None = None
        self._started = asyncio.Event()
        self._final_commit = asyncio.Event()
        self._final_sent = False
        self.error: str | None = None

    @property
    def alive(self) -> bool:
        return self.ws is not None and self._reader is not None and not self._reader.done()

    async def open(self) -> None:
        query = urlencode(
            {
                "model_id": STT_MODEL,
                "audio_format": "pcm_16000",
                "language_code": STT_LANGUAGE,
                "commit_strategy": "vad",
                "vad_silence_threshold_secs": self.vad_silence_secs,
            }
        )
        url = f"{WSS}/v1/speech-to-text/realtime?{query}"
        headers = {"xi-api-key": api_key()}
        self.ws = await connect(url, additional_headers=headers, open_timeout=self.open_timeout)
        self._reader = asyncio.create_task(self._read())
        await asyncio.wait_for(self._started.wait(), self.open_timeout)

    async def _read(self) -> None:
        assert self.ws
        last_partial = ""
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                kind = msg.get("message_type")
                if kind == "session_started":
                    log(f"stt session {msg.get('session_id')}")
                    self._started.set()
                elif kind == "partial_transcript":
                    text = msg.get("text", "")
                    if text and text != last_partial:
                        last_partial = text
                        self.on_partial(text)
                elif kind == "committed_transcript":
                    last_partial = ""
                    if msg.get("text", "").strip():
                        self.on_committed(msg["text"].strip(), time.monotonic())
                    if self._final_sent:
                        self._final_commit.set()
                elif kind in STT_ERRORS:
                    self.error = f"{kind}: {msg.get('error') or msg.get('message') or msg}"
                    log(f"stt {self.error}")
                    if self._final_sent:
                        self._final_commit.set()
        except ConnectionClosed as e:
            log(f"stt socket closed: {e}")
        finally:
            self._final_commit.set()

    async def send(self, frame: bytes, commit: bool = False) -> None:
        assert self.ws
        chunk = {
            "message_type": "input_audio_chunk",
            "audio_base_64": base64.b64encode(frame).decode(),
            "commit": commit,
            "sample_rate": SAMPLE_RATE,
        }
        await asyncio.wait_for(self.ws.send(json.dumps(chunk)), self.send_timeout)

    async def finish(
        self, trailing_silence_secs: float = 2.0, final_wait_secs: float = 5.0
    ) -> None:
        """Trailing silence, a final commit, then wait for the provider before closing,
        or the last words are lost (there is no close message in the Scribe protocol)."""
        if not self.alive:
            await self.close()
            return
        silence = bytes(FRAME_BYTES)
        try:
            for _ in range(round(trailing_silence_secs / FRAME_SECS)):
                await self.send(silence)
            self._final_sent = True
            await self.send(silence, commit=True)
            await asyncio.wait_for(self._final_commit.wait(), final_wait_secs)
        except (TimeoutError, ConnectionClosed):
            log("stt: no committed transcript after the final commit (VAD may have taken it)")
        await self.close()

    async def close(self) -> None:
        if self.ws:
            await self.ws.close()
        if self._reader:
            self._reader.cancel()


async def stream_to_scribe(
    pcm: bytes,
    on_partial: Callable[[str], None],
    on_committed: Callable[[str, float], None],
    *,
    vad_silence_secs: float = 0.8,
    trailing_silence_secs: float = 2.0,
    final_wait_secs: float = 5.0,
) -> float:
    """Stream PCM in real-time 100 ms frames; return the monotonic time speech ended."""
    speech_end = speech_end_offset(pcm)
    stream = ScribeStream(on_partial, on_committed, vad_silence_secs=vad_silence_secs)
    await stream.open()
    frames = [pcm[i : i + FRAME_BYTES] for i in range(0, len(pcm), FRAME_BYTES)]
    start = time.monotonic()
    for n, frame in enumerate(frames):
        await asyncio.sleep(max(0.0, start + n * FRAME_SECS - time.monotonic()))
        await stream.send(frame)
    await stream.finish(trailing_silence_secs, final_wait_secs)
    return start + speech_end


TURN_GAP_SECS = 0.6  # a pause this long starts a new line even for the same speaker label


def speaker_turns(words: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Scribe batch words -> [(speaker, text)]: a new line at every change of speaker label
    and at every pause of TURN_GAP_SECS. Guests who sound alike share a label, so the pauses
    are what keeps one guest's order apart from the next one's."""
    turns: list[tuple[str, str]] = []
    last_end: float | None = None
    for w in words:
        if w.get("type") == "audio_event":
            continue
        speaker = str(w.get("speaker_id") or "speaker")
        text = str(w.get("text", ""))
        start = w.get("start")
        paused = (
            w.get("type") == "word"
            and isinstance(start, int | float)
            and last_end is not None
            and start - last_end >= TURN_GAP_SECS
        )
        if w.get("type") == "word" and isinstance(w.get("end"), int | float):
            last_end = float(w["end"])
        if turns and turns[-1][0] == speaker and not paused:
            turns[-1] = (speaker, turns[-1][1] + text)
        elif text.strip():
            turns.append((speaker, text.strip()))
    return [(s, " ".join(t.split())) for s, t in turns if t.strip()]


async def transcribe_clip(
    pcm: bytes, *, diarize: bool = True, timeout: float = CLIP_STT_TIMEOUT
) -> list[tuple[str, str]]:
    """One batch Scribe call for a clip of raw 16 kHz s16le mono PCM (English pinned).
    The clip is sent from memory and never written to disk here."""
    data = {
        "model_id": BATCH_STT_MODEL,
        "language_code": STT_LANGUAGE,
        "file_format": "pcm_s16le_16",
        "tag_audio_events": "false",
        "diarize": "true" if diarize else "false",
    }
    async with httpx.AsyncClient(timeout=timeout) as http:
        r = await http.post(
            f"{API}/v1/speech-to-text",
            headers={"xi-api-key": api_key()},
            data=data,
            files={"file": ("clip.pcm", pcm, "application/octet-stream")},
        )
    if r.is_error:
        raise ConnectionError(f"scribe batch {r.status_code}: {r.text[:200]}")
    body = r.json()
    turns = speaker_turns(body.get("words") or [])
    if not turns and body.get("text", "").strip():
        turns = [("speaker", body["text"].strip())]
    return turns


class AgentSession:
    """One text-only conversation; client tool calls run against an OrderBook."""

    def __init__(
        self,
        agent_id: str,
        book: OrderBook,
        on_tool: Callable[[str, dict[str, Any], dict[str, Any], bool, float], None],
        on_reply: Callable[[str], None],
    ):
        self.agent_id = agent_id
        self.book = book
        self.on_tool = on_tool
        self.on_reply = on_reply
        self.ws: ClientConnection | None = None
        self._reader: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._replied = asyncio.Event()
        self._last_event = 0.0
        self._tools_in_flight = 0

    async def start(self) -> None:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as http:
            r = await http.get(
                f"{API}/v1/convai/conversation/get-signed-url",
                params={"agent_id": self.agent_id},
                headers={"xi-api-key": api_key()},
            )
            r.raise_for_status()
            signed_url = r.json()["signed_url"]
        self.ws = await connect(signed_url, open_timeout=HTTP_TIMEOUT)
        await self.ws.send(json.dumps({"type": "conversation_initiation_client_data"}))
        self._reader = asyncio.create_task(self._read())
        await asyncio.wait_for(self._ready.wait(), HTTP_TIMEOUT)

    @property
    def alive(self) -> bool:
        return self.ws is not None and self._reader is not None and not self._reader.done()

    async def contextual_update(self, text: str) -> None:
        """Tell the agent what the server did on the glasses (no reply expected)."""
        if self.alive and self.ws:
            payload = json.dumps({"type": "contextual_update", "text": text})
            await asyncio.wait_for(self.ws.send(payload), 2.0)

    async def _read(self) -> None:
        try:
            await self._read_loop()
        except ConnectionClosed as e:
            log(f"agent socket closed: {e}")

    async def _read_loop(self) -> None:
        assert self.ws
        async for raw in self.ws:
            msg = json.loads(raw)
            kind = msg.get("type")
            self._last_event = time.monotonic()
            if kind == "conversation_initiation_metadata":
                cid = msg["conversation_initiation_metadata_event"]["conversation_id"]
                log(f"agent conversation {cid}")
                self._ready.set()
            elif kind == "ping":
                event_id = msg["ping_event"]["event_id"]
                await self.ws.send(json.dumps({"type": "pong", "event_id": event_id}))
            elif kind == "client_tool_call":
                await self._run_tool(msg["client_tool_call"])
            elif kind == "agent_response":
                self.on_reply(msg["agent_response_event"]["agent_response"])
                self._replied.set()
            elif kind == "error" or kind == "client_error":
                log(f"agent {kind}: {msg}")

    async def _run_tool(self, call: dict[str, Any]) -> None:
        assert self.ws
        t = time.monotonic()
        self._tools_in_flight += 1
        try:
            params = call.get("parameters", {})
            result, is_error = self.book.dispatch(call.get("tool_name", ""), params)
            self.on_tool(call.get("tool_name", ""), params, result, is_error, t)
            if call.get("expects_response", True):
                await self.ws.send(
                    json.dumps(
                        {
                            "type": "client_tool_result",
                            "tool_call_id": call["tool_call_id"],
                            "result": json.dumps(result),
                            "is_error": is_error,
                        }
                    )
                )
        finally:
            self._tools_in_flight -= 1
            self._last_event = time.monotonic()

    async def say(self, text: str, turn_timeout: float = 20.0, quiet_secs: float = 0.8) -> None:
        """Send one transcript segment and wait until the agent's turn is over."""
        assert self.ws
        self._replied.clear()
        payload = json.dumps({"type": "user_message", "text": text})
        await asyncio.wait_for(self.ws.send(payload), 2.0)
        deadline = time.monotonic() + turn_timeout
        while time.monotonic() < deadline:
            if not self.alive:
                raise ConnectionError("agent socket closed")
            quiet = time.monotonic() - self._last_event >= quiet_secs
            if self._replied.is_set() and quiet and not self._tools_in_flight:
                return
            await asyncio.sleep(0.05)
        log(f"agent turn timed out after {turn_timeout:.0f} s")

    async def close(self) -> None:
        if self.ws:
            await self.ws.close()
        if self._reader:
            self._reader.cancel()
