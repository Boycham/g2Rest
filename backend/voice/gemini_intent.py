"""Map the words after "verity" that aren't a command word onto one fixed intent, with Gemini.

Server-side only (GEMINI_API_KEY from the environment). Gemini only proposes: code checks the
intent is in the fixed list and the name is one plain word, and anything else is "none". Only
the few words after the wake word are sent, never the conversation.
"""

from __future__ import annotations

import json
import logging
import os
import re

import httpx

from commands import INTENTS

# The same model and env var as the backend's router (backend/app/config.py), so they can't drift.
GEMINI_MODEL = os.environ.get("FS_GEMINI_MODEL", "gemini-3.1-flash-lite")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_TIMEOUT = float(os.environ.get("FS_INTENT_TIMEOUT_SEC", "2"))
# httpx logs request URLs at INFO, and the key rides in the URL.
logging.getLogger("httpx").setLevel(logging.WARNING)

INSTRUCTIONS = """A restaurant server wearing smart glasses said "verity" (the wake word) and then the
words in the user turn. Pick the one glasses action they meant, or "none" if it is not a request to
the glasses. Actions: up (swipe up), down (swipe down), menu (open the controls menu), queue (show the task
queue), back (previous screen / close the menu), confirm (yes / send it / pick), clip (clip the
last 2 minutes of the order), accept (take the task), decline (refuse the task), done (finished the
task), handoff (give the task to someone else; set name if they said who), nevermind (cancel
what is pending), revert (undo the last action), ramp (show what is in the dishes on the current
card: components, allergens and the wine pairing, e.g. "what's in it", "what's on the plate")."""

SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": [*INTENTS, "none"]},
        "name": {"type": "string", "nullable": True},
    },
    "required": ["intent"],
}


class IntentUnavailable(Exception):
    """No key, timeout or a bad reply: the glasses show `Didn't get` with the reason."""


def gemini_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or None


def checked(reply: dict[str, object]) -> tuple[str, str | None] | None:
    """Code decides: a known intent, and for handoff at most one plain-word name."""
    intent = reply.get("intent")
    if intent not in INTENTS:
        return None
    name = reply.get("name")
    ok_name = (
        intent == "handoff" and isinstance(name, str) and re.fullmatch(r"[A-Za-z]{1,20}", name)
    )
    return str(intent), name.capitalize() if ok_name else None  # type: ignore[union-attr]


def request_body(words: str) -> dict[str, object]:
    """Fixed instructions as the system turn and only the spoken words as the user turn."""
    return {
        "systemInstruction": {"parts": [{"text": INSTRUCTIONS}]},
        "contents": [{"role": "user", "parts": [{"text": words}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": SCHEMA,
            "temperature": 0,
            "thinkingConfig": {"thinkingLevel": "MINIMAL"},
        },
    }


async def map_words(
    words: str, *, timeout: float = GEMINI_TIMEOUT
) -> tuple[str, str | None] | None:
    """(intent, name) or None when Gemini says it isn't one; raises IntentUnavailable."""
    key = gemini_key()
    if not key:
        raise IntentUnavailable("no key")
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            r = await http.post(
                GEMINI_URL.format(model=GEMINI_MODEL),
                # ?key=, as the router does: AI Studio AQ. keys get a 404 with x-goog-api-key
                params={"key": key},
                json=request_body(words),
            )
    except httpx.TimeoutException as e:
        raise IntentUnavailable("timeout") from e
    except httpx.HTTPError as e:
        raise IntentUnavailable("offline") from e
    if r.is_error:
        raise IntentUnavailable(f"gemini {r.status_code}")
    try:
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        reply = json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise IntentUnavailable("bad reply") from e
    return checked(reply) if isinstance(reply, dict) else None
