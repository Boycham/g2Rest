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


# ---- clip mode: the last 2 minutes from the glasses' rolling buffer ----


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


HEARD = (
    ("speaker_1", "I'll have the halibut, no butter."),
    ("speaker_1", "The salmon, no dill. I have a shellfish allergy."),
    ("speaker_1", "I'll just get the fish."),
)


def clip_relay(order=CLIP_ORDER, turns=HEARD):
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
    assert sent[-1]["notice"] == "no order heard in the last 2 min"
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


def test_speaker_turns_split_on_speaker_and_on_pauses():
    from voice_session import speaker_turns

    def w(text, start, end, spk="speaker_1"):
        return {"text": text, "start": start, "end": end, "type": "word", "speaker_id": spk}

    def sp(start, end, spk="speaker_1"):
        return {"text": " ", "start": start, "end": end, "type": "spacing", "speaker_id": spk}

    words = [
        w("Welcome.", 0.0, 0.5, "speaker_0"),
        w("Halibut", 1.0, 1.4), sp(1.4, 1.5), w("please.", 1.5, 1.9),
        sp(1.9, 2.8), w("Salmon", 2.8, 3.2), sp(3.2, 3.3), w("for", 3.3, 3.4),
        sp(3.4, 3.45), w("me.", 3.45, 3.6),
        {"text": "(laughs)", "type": "audio_event"},
    ]  # fmt: skip
    assert speaker_turns(words) == [
        ("speaker_0", "Welcome."),
        ("speaker_1", "Halibut please."),
        ("speaker_1", "Salmon for me."),
    ]


@run
async def test_command_stream_sends_only_matched_intents_and_pauses_for_a_clip(monkeypatch):
    import relay

    monkeypatch.setattr(relay, "CMD_GATE_DBFS", None)  # the fake frames are below the default gate
    session, sent, made = clip_relay()
    streams: list[FakeStt] = []

    def make_stt(p, c):
        streams.append(FakeStt(p, c))
        return streams[-1]

    session.make_stt = make_stt
    await session.handle_text('{"type": "capture.start", "captureId": "cmd-1", "mode": "command"}')
    await session.audio(b"\x02" * FRAME_BYTES)
    assert streams[0].frames == [b"\x02" * FRAME_BYTES]
    streams[0].on_committed("We're done here. Verity accept.", 0.0)
    await settle()
    assert sent[-1] == {"type": "voice.command", "intent": "accept"}
    assert all("done" not in json.dumps(m) for m in sent)
    streams[0].on_committed("Verity, ramp on.", 0.0)
    await settle()
    assert sent[-1] == {"type": "voice.command", "intent": "ramp", "toggle": "on"}

    await send_clip(session, frames=2)  # clip frames go to the clip, not the command stream
    assert made["clips"] == [b"\x01" * FRAME_BYTES * 2] and len(streams[0].frames) == 1
    await session.audio(b"\x03" * FRAME_BYTES)  # after the clip: back to commands
    assert len(streams[0].frames) == 2
    await session.close()


@run
async def test_unknown_words_after_the_wake_word_go_to_gemini_or_show_didnt_get():
    import relay as relay_mod
    from gemini_intent import IntentUnavailable

    session, sent, _ = clip_relay()
    streams: list[FakeStt] = []
    session.make_stt = lambda p, c: streams.append(FakeStt(p, c)) or streams[-1]
    replies = iter([("handoff", "Ben"), None, IntentUnavailable("timeout")])

    async def fake_map(words: str):
        r = next(replies)
        if isinstance(r, Exception):
            raise r
        return r

    real = relay_mod.map_words
    relay_mod.map_words = fake_map
    try:
        await session.handle_text(
            '{"type": "capture.start", "captureId": "cmd-1", "mode": "command"}'
        )
        streams[0].on_committed("Verity, give it to Ben.", 0.0)
        await settle()
        assert sent[-1] == {"type": "voice.command", "intent": "handoff", "name": "Ben"}
        streams[0].on_committed("Verity, sing.", 0.0)
        await settle()
        assert sent[-2:] == [
            {"type": "voice.mapping", "words": "sing"},
            {"type": "voice.unknown", "words": "sing"},
        ]
        streams[0].on_committed("Verity, sing louder.", 0.0)
        await settle()
        assert sent[-1] == {"type": "voice.unknown", "words": "sing louder", "reason": "timeout"}
        streams[0].on_committed("Verity, hand off to Maya.", 0.0)
        await settle()
        assert sent[-1] == {"type": "voice.command", "intent": "handoff", "name": "Maya"}
    finally:
        relay_mod.map_words = real
        await session.close()


class TalkAgent(FakeAgent):
    """The clip's second agent: one set_talk per clip, or a failure."""

    def __init__(self, book, on_tool, talk, fail=False):
        super().__init__(book, on_tool, {})
        self.talk, self.fail = talk, fail

    async def say(self, text: str) -> None:
        if self.fail:
            raise ConnectionError("talk agent down")
        result, err = self.book.dispatch("set_talk", self.talk)
        self.on_tool("set_talk", self.talk, result, err, 0.0)


TALK = {
    "summary": "Anniversary, relaxed.",
    "questions": [
        {"guest": 2, "q": "salmon fish?", "kind": "allergen", "dish": "salmon", "allergen": "fish"},
        {"q": "gluten-free bread?", "kind": "dietary", "dish": "bread"},
    ],
}


def talk_relay(talk=TALK, fail=False, order=CLIP_ORDER):
    session, sent, made = clip_relay(order=order)
    session.make_talk_agent = lambda book, on_tool: TalkAgent(book, on_tool, talk, fail)
    return session, sent, made


@run
async def test_clip_talk_agent_adds_summary_and_menu_answers_beside_the_order():
    session, sent, _ = talk_relay()
    await send_clip(session)
    d = sent[-1]
    assert d["lines"] and d["summary"] == "Anniversary, relaxed"
    assert d["answers"] == [
        {"seat": 2, "q": "salmon fish?", "a": "yes, salmon has fish", "known": True},
        {"q": "gluten-free bread?", "a": "not in menu data", "known": False},
    ]
    await session.handle_text(json.dumps({"type": "order.confirm", "orderId": d["orderId"]}))
    assert sent[-1]["status"] == "sent"
    await session.close()


@run
async def test_clip_talk_failure_still_shows_the_order():
    session, sent, _ = talk_relay(fail=True)
    await send_clip(session)
    d = sent[-1]
    assert d["voice"] == "idle" and d["lines"] and d["summary"] == "" and d["answers"] == []
    await session.close()


@run
async def test_clip_with_no_order_still_shows_the_talk():
    session, sent, _ = talk_relay(order={"items": []})
    await send_clip(session)
    d = sent[-1]
    assert d["lines"] == [] and d["summary"] and len(d["answers"]) == 2
    assert d["notice"] is None
    await session.close()


TABLE_LAST = (
    ("speaker_1", "I'll have the halibut, no butter."),
    ("speaker_0", "Lovely. Thanks, that was table four."),
)


@run
async def test_a_table_said_last_in_the_clip_binds_the_draft():
    session, sent, made = clip_relay(turns=TABLE_LAST)
    await send_clip(session, table=None)
    assert sent[-1]["table"] == "T4"
    assert "table 4 (said in a clip)" in made["agent"].heard[0]
    await session.close()


async def say_table(session, n):
    from commands import Command

    await session._command(Command("table", table=n))


@run
async def test_verity_table_binds_a_tableless_draft_and_the_card_updates():
    session, sent, _ = clip_relay()
    await send_clip(session, table=None)
    assert sent[-1]["table"] is None
    await say_table(session, 4)
    draft = [m for m in sent if m["type"] == "order.draft"][-1]
    assert draft["table"] == "T4" and draft["notice"] is None
    assert sent[-1] == {"type": "voice.command", "intent": "table", "table": "T4"}
    await session.close()


@run
async def test_verity_table_overrides_the_order_task_and_says_what_changed():
    session, sent, _ = clip_relay()
    await send_clip(session, table="T3")
    await say_table(session, 4)
    assert sent[-1] == {"type": "voice.command", "intent": "table", "table": "T4", "was": "T3"}
    assert [m for m in sent if m["type"] == "order.draft"][-1]["table"] == "T4"
    await session.close()


@run
async def test_verity_table_refuses_unknown_tables_sent_orders_and_no_order():
    session, sent, _ = clip_relay()
    await say_table(session, 4)
    assert sent[-1]["reason"] == "no order to set the table for"
    await send_clip(session, table=None)
    await say_table(session, 12)
    assert sent[-1] == {"type": "voice.command", "intent": "table", "table": "T12",
                        "reason": "no table 12"}  # fmt: skip
    await say_table(session, None)
    assert sent[-1]["reason"].startswith("say verity table")
    await say_table(session, 4)
    d = sent[-2]
    await session.handle_text(json.dumps({"type": "order.confirm", "orderId": d["orderId"]}))
    assert sent[-1]["status"] == "sent"
    await say_table(session, 2)
    assert sent[-1]["reason"] == "already sent"
    await session.close()


def test_loudness_gate_zeroes_quiet_frames_and_holds_after_loud_ones():
    import array

    from relay import LoudnessGate

    def frame(amp: int) -> bytes:
        return array.array("h", [amp, -amp] * (FRAME_BYTES // 4)).tobytes()

    loud, quiet, silent = frame(8000), frame(300), bytes(FRAME_BYTES)  # -12, -41 dBFS
    gate = LoudnessGate(-30.0, hold=2)
    assert [gate(f) for f in (quiet, loud, quiet, quiet, quiet)] == [
        silent,
        loud,
        quiet,
        quiet,
        silent,
    ]
    assert LoudnessGate(None)(quiet) == quiet


def test_crowd_settings_come_from_env(monkeypatch):
    from relay import env_float

    monkeypatch.setenv("X_GATE", "-31.5")
    assert env_float("X_GATE", -30.0) == -31.5
    monkeypatch.setenv("X_GATE", "off")
    assert env_float("X_GATE", -30.0) is None
    monkeypatch.setenv("X_GATE", "")
    assert env_float("X_GATE", -30.0) == -30.0


@run
async def test_command_frames_pass_the_loudness_gate():
    import relay as relay_mod

    session, _, _ = clip_relay()
    streams: list[FakeStt] = []
    session.make_stt = lambda p, c: streams.append(FakeStt(p, c)) or streams[-1]
    real = relay_mod.CMD_GATE_DBFS
    relay_mod.CMD_GATE_DBFS = -30.0
    try:
        await session.handle_text('{"type": "capture.start", "captureId": "c", "mode": "command"}')
        await session.audio(b"\x01\x00" * (FRAME_BYTES // 2))  # -90 dBFS: far talk
    finally:
        relay_mod.CMD_GATE_DBFS = real
    assert streams[0].frames == [bytes(FRAME_BYTES)]
    await session.close()


# ---- order clips: a neighbouring table's speaker never reaches the draft ----

TWO_TABLES = [  # (speaker label, start s, words, level dBFS): table near, neighbour ~18 dB down
    ("speaker_0", 0.0, "I'll have the halibut, no butter.", -16.0),
    ("speaker_1", 2.5, "Can we get the ribeye, medium rare?", -34.0),
    ("speaker_0", 5.0, "The salmon for me, please.", -17.0),
    ("speaker_1", 7.5, "And the duck breast.", -35.0),
]


def two_table_clip(same_label: bool = False) -> tuple[dict, bytes]:
    """A mixed two-speaker clip: PCM with each line's words at its level, and the batch
    Scribe response (word timings plus diarization labels) for it."""
    import array
    import math

    secs = 10.0
    pcm = array.array("h", bytes(int(secs * 16000) * 2))
    words: list[dict] = []
    for speaker, start, text, db in TWO_TABLES:
        amp = int(32768 * 10 ** (db / 20) * math.sqrt(2))
        for k, token in enumerate(text.split()):
            a, b = start + 0.35 * k, start + 0.35 * k + 0.3
            for i in range(int(a * 16000), int(b * 16000)):
                pcm[i] = int(amp * math.sin(2 * math.pi * 220 * i / 16000))
            label = "speaker_0" if same_label else speaker
            words.append({"type": "word", "text": token, "start": a, "end": b, "speaker_id": label})
            words.append({"type": "spacing", "text": " ", "speaker_id": label})
    body = {"text": " ".join(t for _, _, t, _ in TWO_TABLES), "words": words}
    return body, pcm.tobytes()


class HearingAgent(ClipAgent):
    """Orders every dish it reads in the clip message, one guest per line: an agent that
    can't tell tables apart, so only the relay's transcript decides what leaks."""

    DISHES = ("halibut", "salmon", "ribeye", "duck")

    async def say(self, text: str) -> None:
        self.heard.append(text)
        items = [
            {"guest": n, "dish": d, "alterations": []}
            for n, line in enumerate(text.splitlines()[1:], 1)
            for d in self.DISHES
            if d in line.lower()
        ]
        order = {"items": items, "allergies": [], "unclear": [], "notes": []}
        result, err = self.book.dispatch("set_order", order)
        self.on_tool("set_order", order, result, err, 0.0)


async def two_table_draft(drop: bool = True, same_label: bool = False) -> tuple[list[str], str]:
    from voice_session import clip_turns

    body, pcm = two_table_clip(same_label)
    sent: list[dict[str, Any]] = []
    made: dict[str, Any] = {}

    async def send(msg):
        sent.append(msg)

    def make_agent(book, on_tool):
        made["agent"] = HearingAgent(book, on_tool, None)
        return made["agent"]

    async def transcribe(clip: bytes):
        return clip_turns(body, pcm, drop_other_tables=drop)[0]

    session = RelaySession(send, lambda p, c: FakeStt(p, c), make_agent, transcribe)
    await send_clip(session)
    await session.close()
    return [ln["dish"] for ln in sent[-1]["lines"]], made["agent"].heard[0]


@run
async def test_neighbouring_table_dishes_never_reach_the_draft():
    dishes, heard = await two_table_draft()
    assert dishes == ["halibut", "salmon"]
    assert "speaker_0: I'll have the halibut" in heard and "speaker_1" not in heard


@run
async def test_the_speaker_labels_are_what_keeps_the_other_table_out():
    dishes, heard = await two_table_draft(drop=False)  # labels passed through, no rule
    assert "ribeye" in dishes and "speaker_1: Can we get the ribeye" in heard
    dishes, _ = await two_table_draft(same_label=True)  # diarization merged both tables
    assert "ribeye" in dishes


def test_other_tables_rule():
    from voice_session import other_tables

    def drop(levels):
        return other_tables(levels, quiet_db=8.0)

    assert drop({"a": (40, -18.0), "b": (12, -30.0)}) == {"b"}  # much quieter
    assert drop({"a": (40, -18.0), "b": (4, -23.0)}) == {"b"}  # quieter, few words
    assert drop({"a": (40, -18.0), "b": (3, -19.0)}) == set()  # short but near
    assert drop({"a": (40, -18.0), "b": (30, -23.0)}) == set()  # a quieter guest
    assert drop({"a": (40, -40.0)}) == set()  # one speaker is always the table
    # the wearer right at the mic: guests are measured against the loudest guest instead
    wearer = {"server": (50, -8.0), "g1": (12, -26.0), "g2": (9, -29.0), "far": (14, -37.0)}
    assert drop(wearer) == {"far"}
    assert other_tables({"a": (40, -18.0), "b": (12, -30.0)}, quiet_db=None) == {"b"}


@run
async def test_menu_86_from_the_backend_reaches_the_order_book(relay):
    session, _, _ = await relay()
    await session.handle_text(json.dumps({"type": "menu.86", "dishes": ["Pan-Roasted Halibut"]}))
    assert session.book.out == {"Pan-Roasted Halibut"}
    await session.handle_text(json.dumps({"type": "menu.86", "dishes": []}))
    assert session.book.out == set()
    await session.close()
