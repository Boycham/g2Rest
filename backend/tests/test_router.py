from __future__ import annotations

import asyncio
import json

import httpx

from app import router
from app.config import DATA_DIR, Settings
from app.state import Store


def store(key: str = "k") -> Store:
    return Store.from_settings(Settings(data_dir=DATA_DIR, gemini_api_key=key))


def gemini(reply):  # noqa: ANN001, ANN201 - an AsyncClient that answers with `reply`
    seen: dict = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return reply(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handle)), seen


def answer(text: str):  # noqa: ANN201
    return lambda _: httpx.Response(
        200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]}
    )


def pick(s: Store, client: httpx.AsyncClient, table: str = "T1") -> str:
    return asyncio.run(router.pick(s, client, "CHECK", table, []))


def picks(s: Store) -> list[dict]:
    return [e.data for e in s.events.of_type("router.pick")]


def test_gemini_pick_wins_and_is_logged() -> None:
    s = store()
    client, seen = gemini(answer("s2"))
    assert pick(s, client) == "s2"  # T1 is s1's section; Gemini chose otherwise
    assert seen["generationConfig"]["responseSchema"]["enum"] == ["s1", "s2"]
    ev = picks(s)[-1]
    assert (ev["how"], ev["assignee"], ev["rule"]) == ("gemini", "s2", "s1")


def test_rules_when_gemini_answers_nonsense_errors_or_times_out() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    s = store()
    for reply in (
        answer("m1"),
        lambda _: httpx.Response(503),
        lambda _: httpx.Response(200, json={}),
        slow,
    ):
        assert pick(s, gemini(reply)[0]) == "s1"
    assert [e["how"] for e in picks(s)] == ["rules"] * 4


def test_no_key_means_rules_and_no_call() -> None:
    def boom(_: httpx.Request) -> httpx.Response:
        raise AssertionError("called Gemini without a key")

    assert pick(store(key=""), gemini(boom)[0]) == "s1"
