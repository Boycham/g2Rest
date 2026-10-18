import asyncio
import functools
import json
from typing import Any

import pytest

from relay import RelaySession, build_draft
from voice_session import FRAME_BYTES


class FakeStt:
    def __init__(self, on_partial, on_committed, fail: bool = False):
        self.on_committed = on_committed
        self.fail = fail
        self.frames: list[bytes] = []
        self.opened = False
        self.finished = False

    @property
    def alive(self) -> bool:
        return self.opened and not self.finished

    async def open(self) -> None:
        if self.fail:
            raise TimeoutError("scribe did not answer")
        self.opened = True

    async def send(self, frame: bytes, commit: bool = False) -> None:
        self.frames.append(frame)

    async def finish(self) -> None:
        self.finished = True

    async def close(self) -> None:
        self.finished = True


class FakeAgent:
    """Turns each committed segment into scripted tool calls on the real OrderBook."""

    def __init__(self, book, on_tool, script: dict[str, list[tuple[str, dict]]]):
        self.book = book
        self.on_tool = on_tool
        self.script = script
        self.updates: list[str] = []

    @property
    def alive(self) -> bool:
        return True

    async def start(self) -> None:
        pass

    async def say(self, text: str) -> None:
        for tool, params in self.script.get(text, []):
            result, err = self.book.dispatch(tool, params)
            self.on_tool(tool, params, result, err, 0.0)

    async def contextual_update(self, text: str) -> None:
        self.updates.append(text)

    async def close(self) -> None:
        pass


def run(fn):
    """Plain asyncio.run per test, so no pytest-asyncio dependency."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return wrapper


SCRIPT = {
    "order": [
        ("add_item", {"table": 12, "seat": 1, "dish": "halibut", "alterations": ["no butter"]}),
        ("add_item", {"table": 12, "seat": 2, "dish": "salmon", "alterations": ["no dill"]}),
        ("add_item", {"table": 12, "seat": 2, "dish": "soup"}),
    ],
    "no suit": [("remove_item", {"table": 12, "seat": 2, "dish": "suit"})],
    "no soup": [("remove_item", {"table": 12, "seat": 2, "dish": "soup"})],
    "no torte": [("remove_item", {"table": 12, "seat": 1, "dish": "torte"})],
}


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.fixture
def relay():
    sent: list[dict[str, Any]] = []
    made: dict[str, Any] = {}

    async def send(msg):
        sent.append(msg)

    def make_stt(p, c):
        made["stt"] = FakeStt(p, c, fail=made.get("fail_stt", False))
        return made["stt"]

    def make_agent(book, on_tool):
        made["agent"] = FakeAgent(book, on_tool, SCRIPT)
        return made["agent"]

    async def build():
        return RelaySession(send, make_stt, make_agent), sent, made

    return build


async def say(session, made, text: str) -> None:
    made["stt"].on_committed(text, 0.0)
    await settle()


def test_build_draft_by_seat_with_pinned_allergy():
    from order import Menu, OrderBook

    book = OrderBook(Menu.load())
    book.dispatch(
        "add_item", {"table": 12, "seat": 1, "dish": "halibut", "alterations": ["no butter"]}
    )
    book.dispatch("set_allergy", {"table": 12, "seat": 3, "allergen": "shellfish"})
    removal, _ = book.dispatch("remove_item", {"table": 12, "seat": 1, "dish": "halibut"})
    draft = build_draft(book, "o1", "c1", "listening", None)
    assert draft["table"] == "T12"
    assert draft["lines"] == [
        {"seat": 1, "qty": 1, "dish": "halibut", "alterations": ["no butter"], "flagged": []}
    ]
    assert draft["allergies"] == [{"allergen": "SHELLFISH", "seats": [3]}]
    assert draft["pending"] == [
        {"id": removal["id"], "action": "remove", "text": "REMOVE s1 halibut?"}
    ]


@run
async def test_capture_flow_proposals_and_confirm(relay):
    session, sent, made = await relay()
    await session.handle_text(json.dumps({"type": "capture.start", "captureId": "c1"}))
    assert [m["voice"] for m in sent] == ["connecting", "listening"]
    await session.audio(bytes(FRAME_BYTES))
    await session.audio(b"short")
    assert len(made["stt"].frames) == 1

    await say(session, made, "order")
    draft = sent[-1]
    assert [(l["seat"], l["dish"]) for l in draft["lines"]] == [
        (1, "halibut"),
        (2, "salmon"),
        (2, "soup"),
    ]

    await say(session, made, "no torte")
    assert sent[-1]["notice"] == "s1 has no chocolate torte: nothing removed"
    assert sent[-1]["pending"] == []

    await say(session, made, "no soup")
    pending = sent[-1]["pending"]
    assert [p["text"] for p in pending] == ["REMOVE s2 soup?"]
    assert len(sent[-1]["lines"]) == 3  # not removed yet

    order_id = sent[-1]["orderId"]
    await session.handle_text(
        json.dumps({"type": "order.confirm", "orderId": order_id, "proposalId": pending[0]["id"]})
    )
    assert [(l["seat"], l["dish"]) for l in sent[-1]["lines"]] == [(1, "halibut"), (2, "salmon")]
    assert sent[-1]["pending"] == [] and made["agent"].updates

    await session.handle_text(json.dumps({"type": "capture.stop", "captureId": "c1"}))
    assert sent[-1]["voice"] == "idle"
    await settle()
    assert made["stt"].finished

    await session.handle_text(json.dumps({"type": "order.confirm", "orderId": order_id}))
    assert sent[-1]["status"] == "sent"
    await session.close()


@run
async def test_swipe_up_rejects_noisy_removal(relay):
    session, sent, made = await relay()
    await session.capture_start("c1")
    await say(session, made, "order")
    made["agent"].script["no suit"] = [("remove_item", {"table": 12, "seat": 2, "dish": "salmon"})]
    await say(session, made, "no suit")
    pending = sent[-1]["pending"][0]
    assert pending["text"] == "REMOVE s2 salmon?"
    await session.handle_text(
        json.dumps(
            {"type": "order.reject", "orderId": session.order_id, "proposalId": pending["id"]}
        )
    )
    assert ("salmon" in [l["dish"] for l in sent[-1]["lines"]]) and sent[-1]["pending"] == []
    await session.close()


@run
async def test_confirm_with_pending_is_refused(relay):
    session, sent, made = await relay()
    await session.capture_start("c1")
    await say(session, made, "order")
    await say(session, made, "no soup")
    await session.handle_text(json.dumps({"type": "order.confirm", "orderId": session.order_id}))
    assert sent[-1]["status"] == "draft" and "pending" in sent[-1]["notice"]
    await session.close()


@run
async def test_stale_order_id_is_ignored(relay):
    session, sent, made = await relay()
    await session.capture_start("c1")
    await say(session, made, "order")
    await session.handle_text(json.dumps({"type": "order.confirm", "orderId": "old"}))
    assert sent[-1]["status"] == "draft"
    await session.close()


@run
async def test_provider_failure_shows_voice_offline(relay):
    session, sent, made = await relay()
    made["fail_stt"] = True
    await session.capture_start("c1")
    assert sent[-1]["voice"] == "offline"
    await session.audio(bytes(FRAME_BYTES))  # dropped, no crash
    await session.close()


@run
async def test_new_order_after_send(relay):
    session, sent, made = await relay()
    await session.capture_start("c1")
    await say(session, made, "order")
    first = session.order_id
    await session.handle_text(json.dumps({"type": "order.confirm", "orderId": first}))
    await session.capture_start("c2")
    assert session.order_id != first and sent[-1]["lines"] == []
    await session.close()


# ---- clip mode: the last minute from the glasses' rolling buffer ----


class ClipAgent(FakeAgent):
    """Answers every clip with one set_order call, like the clip agent."""

    def __init__(self, book, on_tool, order):
        super().__init__(book, on_tool, {})
        self.order = order
        self.heard: list[str] = []

    async def say(self, text: str) -> None:
        self.heard.append(text)
        if self.order is not None:
            result, err = self.book.dispatch("set_order", self.order)
            self.on_tool("set_order", self.order, result, err, 0.0)


CLIP_ORDER = {
    "items": [
        {"guest": 1, "dish": "halibut", "alterations": ["no butter"]},
        {"guest": 2, "dish": "salmon", "alterations": ["no dill"]},
    ],
    "allergies": [{"guest": 2, "allergen": "shellfish"}],
    "unclear": [{"guest": 3, "text": "'the fish': halibut or salmon"}],
    "notes": ["anniversary"],
}


def clip_relay(order=CLIP_ORDER, turns=(("speaker_0", "I'll have the halibut"),)):
    sent: list[dict[str, Any]] = []
    made: dict[str, Any] = {"clips": []}

    async def send(msg):
        sent.append(msg)

    def make_agent(book, on_tool):
        made["agent"] = ClipAgent(book, on_tool, order)
        return made["agent"]

    async def transcribe(pcm: bytes):
        made["clips"].append(pcm)
        return list(turns)

    session = RelaySession(send, lambda p, c: FakeStt(p, c), make_agent, transcribe)
    return session, sent, made


async def send_clip(session, frames: int = 3, table: str | None = "T3") -> None:
    start = {"type": "capture.start", "captureId": "clip-1", "mode": "clip"}
    if table:
        start["table"] = table
    await session.handle_text(json.dumps(start))
    for _ in range(frames):
        await session.audio(b"\x01" * FRAME_BYTES)
    await session.handle_text('{"type": "capture.stop", "captureId": "clip-1"}')
    for _ in range(20):
        await asyncio.sleep(0)


@run
async def test_clip_for_an_order_task_builds_the_draft_by_seat():
    session, sent, made = clip_relay()
    await send_clip(session)
    assert sent[0]["voice"] == "processing" and sent[0]["table"] == "T3"
    assert made["clips"] == [b"\x01" * FRAME_BYTES * 3] and session.clip == bytearray()
    assert "table 3 (from the ORDER task)" in made["agent"].heard[0]
    d = sent[-1]
    assert d["voice"] == "idle" and d["table"] == "T3"
    assert [(ln["seat"], ln["dish"], ln["alterations"]) for ln in d["lines"]] == [
        (1, "halibut", ["no butter"]),
        (2, "salmon", ["no dill"]),
    ]
    assert d["allergies"] == [{"allergen": "SHELLFISH", "seats": [2]}]
    assert d["uncertain"] == ["? s3 'the fish': halibut or salmon"]
    assert d["notes"] == ["anniversary"]
    await session.handle_text(json.dumps({"type": "order.confirm", "orderId": d["orderId"]}))
    assert sent[-1]["status"] == "sent"
    await session.close()


@run
async def test_tableless_clip_cannot_be_sent_until_the_table_is_spoken():
    session, sent, made = clip_relay()
    await send_clip(session, table=None)
    d = sent[-1]
    assert d["table"] is None and d["lines"]
    await session.handle_text(json.dumps({"type": "order.confirm", "orderId": d["orderId"]}))
    assert sent[-1]["status"] == "draft" and "TABLE?" in sent[-1]["notice"]
    made["agent"].order = {**CLIP_ORDER, "table": 2}
    await send_clip(session, table=None)
    assert sent[-1]["table"] == "T2"
    await session.handle_text(json.dumps({"type": "order.confirm", "orderId": d["orderId"]}))
    assert sent[-1]["status"] == "sent" and sent[-1]["table"] == "T2"
    await session.close()


@run
async def test_small_talk_clip_adds_nothing_and_says_so():
    session, sent, _ = clip_relay(order=None, turns=(("speaker_0", "How was the theater?"),))
    await send_clip(session)
    assert sent[-1]["lines"] == [] and sent[-1]["voice"] == "idle"
    assert sent[-1]["notice"] == "no order heard in the last minute"
    await session.close()


@run
async def test_clip_transcription_failure_shows_voice_offline():
    session, sent, _ = clip_relay()

    async def broken(pcm: bytes):
        raise ConnectionError("scribe batch 503")

    session.transcribe = broken
    await send_clip(session)
    assert sent[-1]["voice"] == "offline"
    await session.close()


def test_table_number_parses_labels():
    from relay import table_number

    assert [table_number(x) for x in ("T3", "12", "t2", "", None, "T0", "bar")] == [
        3, 12, 2, None, None, None, None,
    ]  # fmt: skip
