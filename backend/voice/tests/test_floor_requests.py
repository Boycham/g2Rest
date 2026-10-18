"""Floor requests and table statuses, said in a clip or after "verity"."""

import pytest
from test_commands import NEVER_FIRE
from test_relay import clip_relay, run, send_clip

import make_fixtures
from commands import Command, keyterms, parse_commands
from floor_requests import STATUSES, Request, parse_request, requests_in
from gemini_intent import checked
from order import Menu, ToolError

MENU = Menu.load()


def is_dish(words: str) -> bool:
    try:
        MENU.resolve(words)
    except ToolError:
        return False
    return True


CLIP_PHRASES = {
    "table 2 wants the check": Request(2, kind="CHECK", status="check"),
    "Table two wants the check.": Request(2, kind="CHECK", status="check"),
    "T4 needs bread": Request(4, kind="RUN", note="bread"),
    "Six needs more water.": Request(6, kind="RUN", note="water"),
    "Clear table three.": Request(3, kind="CLEAR"),
    "T5 is ready to order.": Request(5, kind="ORDER"),
    "Table 7 is asking for the bill.": Request(7, kind="CHECK", status="check"),
    "Table one would like a water refill.": Request(1, kind="RUN", note="water refill"),
    "Table eight needs clearing.": Request(8, kind="CLEAR"),
}


@pytest.mark.parametrize("text", CLIP_PHRASES)
def test_each_request_phrase_in_a_clip(text):
    assert requests_in(f"Sure, thanks. {text} Anything else?", is_dish) == [CLIP_PHRASES[text]]


VOICE_PHRASES = {
    "verity table 2 wants the check": Request(2, kind="CHECK", status="check"),
    "Verity, T4 needs bread.": Request(4, kind="RUN", note="bread"),
    "verity six needs more water": Request(6, kind="RUN", note="water"),
    "Verity clear table three.": Request(3, kind="CLEAR"),
    "verity T5 is ready to order": Request(5, kind="ORDER"),
}


@pytest.mark.parametrize("text", VOICE_PHRASES)
def test_each_request_phrase_by_voice(text):
    assert parse_commands(text) == [Command("request", request=VOICE_PHRASES[text])]


# Every status the backend has (backend/app/data.py TABLE_STATUSES), said a few ways.
STATUS_PHRASES = {
    "verity table 2 paid": Request(2, status="empty", note="paid"),
    "verity table five is free": Request(5, status="empty"),
    "verity table 6 is empty": Request(6, status="empty"),
    "verity T4 seated four": Request(4, status="seated"),
    "verity table 7 VIP seated": Request(7, status="seated", vip=True),
    "verity table 1 ordered": Request(1, status="ordered"),
    "verity table 3 has ordered": Request(3, status="ordered"),
    "verity table 4 is waiting on mains": Request(4, status="waiting", note="on mains"),
    "verity table 8 eating": Request(8, status="eating"),
    "verity table 6 has their food": Request(6, status="eating"),
    "verity table 3 wants the check": Request(3, kind="CHECK", status="check"),
    "verity table 2 check": Request(2, kind="CHECK", status="check"),
}


@pytest.mark.parametrize("text", STATUS_PHRASES)
def test_each_table_status_by_voice(text):
    assert parse_commands(text) == [Command("request", request=STATUS_PHRASES[text])]


def test_every_backend_status_can_be_said():
    said = {r.status for r in STATUS_PHRASES.values()}
    assert said == set(STATUSES) == {"empty", "seated", "ordered", "waiting", "eating", "check"}


def test_bare_verity_table_n_is_still_set_table():
    assert parse_commands("Verity, table four.") == [Command("table", table=4)]
    assert parse_commands("verity table 2") == [Command("table", table=2)]
    assert parse_commands("Verity table number 12.") == [Command("table", table=12)]
    assert parse_commands("Verity, table for.") == [Command("table", table=4)]
    assert parse_commands("Verity table. Verity accept.") == [Command("table"), Command("accept")]
    assert parse_commands("verity table 4, done") == [Command("table", table=4)]
    # "verity clear" alone is still the clip soundalike
    assert parse_commands("Verity, clear.") == [Command("clip")]


def test_orders_and_table_talk_are_not_requests():
    for text in (
        "Table two, the salmon, no dill.",
        "Table 2 wants the halibut.",
        "Could we get a table for two by the window?",
        "That was table four.",
        "T4 needs a minute.",
        "Seat two needs a fork.",
        "Could you verify the bill for us?",
        "Everyone wants the check eventually.",
    ):
        assert requests_in(text, is_dish) == [], text
    # statuses only by voice: "table two is free" in a clip proposes nothing
    assert requests_in("Is table two free tonight? Table two is free.", is_dish) == []


def test_no_false_triggers_on_the_conversation_set():
    for name, lines in make_fixtures.CONVERSATIONS.items():
        text = " ".join(t for _, t in lines)
        assert requests_in(text, is_dish) == [], name
        assert [c for c in parse_commands(text) if c.intent == "request"] == [], name
    for phrase in NEVER_FIRE:
        assert requests_in(phrase, is_dish) == [] and parse_commands(phrase) == [], phrase


def test_a_clip_proposes_each_table_and_kind_once():
    text = "Table 2 wants the check. Yes, table two wants the check. T4 needs bread."
    assert requests_in(text, is_dish) == [
        Request(2, kind="CHECK", status="check"),
        Request(4, kind="RUN", note="bread"),
    ]
    assert parse_request("table 2 wants the check", voice=True) == Request(
        2, kind="CHECK", status="check"
    )


def test_gemini_request_is_checked_by_code():
    ok = {"intent": "request", "table": 2, "kind": "CHECK"}
    assert checked(ok) == Request(2, kind="CHECK")
    assert checked({"intent": "request", "table": 3, "status": "check"}) == Request(
        3, kind="CHECK", status="check"
    )
    assert checked({"intent": "request", "table": 4, "kind": "RUN", "note": "bread"}) == Request(
        4, kind="RUN", note="bread"
    )
    assert checked({"intent": "request", "table": 7, "status": "seated", "vip": True}) == Request(
        7, status="seated", vip=True
    )
    for bad in (
        {"intent": "request", "kind": "CHECK"},
        {"intent": "request", "table": 0, "kind": "CHECK"},
        {"intent": "request", "table": True, "kind": "CHECK"},
        {"intent": "request", "table": 2, "kind": "FIRE"},
        {"intent": "request", "table": 2, "status": "paid"},
        {"intent": "request", "table": 2, "kind": "RUN"},
        {"intent": "request", "table": 2},
    ):
        assert checked(bad) is None, bad
    long = {"intent": "request", "table": 4, "kind": "RUN", "note": "x" * 80}
    assert checked(long) is None


def test_request_words_are_keyterms_within_the_limit():
    terms = keyterms()
    assert len(terms) <= 50
    assert {"check", "bill", "bread", "water", "refill", "seated", "free", "paid"} <= set(terms)
    assert "Dark Chocolate Torte" in terms and "Cheese Plate" in terms  # dishes still fit


def requests_sent(sent):
    return [m for m in sent if m["type"] == "voice.request"]


@run
async def test_clip_request_goes_to_the_glasses_to_confirm():
    session, sent, _ = clip_relay(
        order=None, turns=(("speaker_0", "Table 2 wants the check, thanks."),)
    )
    await send_clip(session)
    assert requests_sent(sent) == [
        {"type": "voice.request", "table": "T2", "kind": "CHECK", "status": "check",
         "source": "clip"}
    ]  # fmt: skip
    assert sent[-1]["type"] == "order.draft" and sent[-1]["notice"] is None
    await session.close()


@run
async def test_voice_request_and_wrong_table():
    session, sent, _ = clip_relay()
    for cmd in parse_commands("verity T4 needs bread. verity table 12 wants the check"):
        await session._command(cmd)
    assert requests_sent(sent) == [
        {"type": "voice.request", "table": "T4", "kind": "RUN", "note": "bread",
         "source": "voice"},
        {"type": "voice.request", "table": "T12", "kind": "CHECK", "status": "check",
         "source": "voice", "reason": "no table 12"},
    ]  # fmt: skip
    await session.close()


@run
async def test_gemini_mapped_request_takes_the_same_path(monkeypatch):
    import relay

    async def fake_map(words):
        assert words == "the two top is done paying"
        return Request(2, status="empty", note="paid")

    monkeypatch.setattr(relay, "map_words", fake_map)
    session, sent, _ = clip_relay()
    await session._command(Command("unknown", words="the two top is done paying"))
    assert requests_sent(sent)[-1] == {
        "type": "voice.request", "table": "T2", "status": "empty", "note": "paid",
        "source": "voice",
    }  # fmt: skip
    await session.close()
