import asyncio
import json
import os
import subprocess
import sys

import httpx
import pytest

import gemini_intent
from gemini_intent import IntentUnavailable, checked, map_words

REAL_CLIENT = httpx.AsyncClient


def test_code_checks_what_gemini_proposes():
    assert checked({"intent": "handoff", "name": "maya"}) == ("handoff", "Maya")
    assert checked({"intent": "accept", "name": "Maya"}) == ("accept", None)
    assert checked({"intent": "handoff", "name": "Maya; DROP"}) == ("handoff", None)
    assert checked({"intent": "send_order"}) is None
    assert checked({"intent": "none"}) is None


def _reply(payload: dict) -> httpx.Response:
    text = json.dumps(payload)
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def _patch(monkeypatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def client(**kw):
        return REAL_CLIENT(transport=httpx.MockTransport(wrapped), **kw)

    monkeypatch.setattr(gemini_intent.httpx, "AsyncClient", client)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    return seen


def test_maps_words_and_sends_only_the_words(monkeypatch):
    seen = _patch(monkeypatch, lambda r: _reply({"intent": "handoff", "name": "Ben"}))
    assert asyncio.run(map_words("give it to ben")) == ("handoff", "Ben")
    body = json.loads(seen[0].content)
    assert body["contents"][0]["parts"][0]["text"] == "give it to ben"
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "MINIMAL"}
    assert seen[0].url.params["key"] == "test-key"
    assert "x-goog-api-key" not in seen[0].headers
    assert gemini_intent.GEMINI_MODEL in seen[0].url.path


def test_none_is_none(monkeypatch):
    _patch(monkeypatch, lambda r: _reply({"intent": "none"}))
    assert asyncio.run(map_words("is lovely")) is None


def _settings(env: dict[str, str]) -> list[str]:
    code = "import gemini_intent as g; print(g.GEMINI_MODEL); print(g.GEMINI_TIMEOUT)"
    clean = {k: v for k, v in os.environ.items() if not k.startswith("FS_")}
    out = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        env={**clean, **env},
        capture_output=True,
        text=True,
    )
    return out.stdout.split()


def test_model_and_timeout_come_from_the_router_env():
    assert _settings({}) == ["gemini-3.1-flash-lite", "2.0"]
    assert _settings({"FS_GEMINI_MODEL": "gemini-x", "FS_INTENT_TIMEOUT_SEC": "1.25"}) == [
        "gemini-x",
        "1.25",
    ]


def test_failures_are_reasons_not_crashes(monkeypatch):
    def slow(r):
        raise httpx.ReadTimeout("slow", request=r)

    _patch(monkeypatch, slow)
    with pytest.raises(IntentUnavailable, match="timeout"):
        asyncio.run(map_words("give it to ben"))
    _patch(monkeypatch, lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(IntentUnavailable, match="gemini 500"):
        asyncio.run(map_words("give it to ben"))
    _patch(monkeypatch, lambda r: httpx.Response(200, json={"candidates": []}))
    with pytest.raises(IntentUnavailable, match="bad reply"):
        asyncio.run(map_words("give it to ben"))
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(IntentUnavailable, match="no key"):
        asyncio.run(map_words("give it to ben"))
