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
from floor_requests import STATUS_TASK, STATUSES, TASK_KINDS, Request

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
card: components, allergens and the wine pairing, e.g. "what's in it", "what's on the plate"),
request (a floor request or table status for one table: set table to its number, and kind for
work to do: CHECK (wants the check / bill / to pay), RUN (bring something: note says what, e.g.
"bread", "water refill"), CLEAR (needs clearing / bussing), ORDER (ready to order); and/or status
for the table: empty (free, paid, left), seated (set vip if VIP), ordered, waiting (waiting on a
course; note says which), eating (food is down), check (wants the check)). A table number alone
("table four") is not a request."""

SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": [*INTENTS, "none"]},
        "name": {"type": "string", "nullable": True},
        "table": {"type": "integer", "nullable": True},
        "kind": {"type": "string", "enum": list(TASK_KINDS), "nullable": True},
        "status": {"type": "string", "enum": list(STATUSES), "nullable": True},
        "vip": {"type": "boolean", "nullable": True},
        "note": {"type": "string", "nullable": True},
    },
    "required": ["intent"],
}


class IntentUnavailable(Exception):
    """No key, timeout or a bad reply: the glasses show `Didn't get` with the reason."""


def gemini_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or None


Mapped = tuple[str, str | None] | Request
NOTE_RE = re.compile(r"[A-Za-z][A-Za-z ,'-]{0,39}")


def checked_request(reply: dict[str, object]) -> Request | None:
    """A request needs a table number and a known kind or status; the note is a few words."""
    table, kind, status = reply.get("table"), reply.get("kind"), reply.get("status")
    if not isinstance(table, int) or isinstance(table, bool) or not 1 <= table <= 999:
        return None
    kind = kind if kind in TASK_KINDS else None
    status = status if status in STATUSES else None
    if status and not kind:
        kind = STATUS_TASK.get(status)
    if not kind and not status:
        return None
    note = reply.get("note")
    note = note.strip() if isinstance(note, str) and NOTE_RE.fullmatch(note.strip()) else None
    if kind == "RUN" and not note:
        return None
    return Request(
        table,
        kind=kind,
        status=status,
        vip=status == "seated" and reply.get("vip") is True,
        note=note,
    )


def checked(reply: dict[str, object]) -> Mapped | None:
    """Code decides: a known intent, for handoff at most one plain-word name, and for a
    request a valid table and kind or status (the floor check is the relay's)."""
    intent = reply.get("intent")
    if intent == "request":
        return checked_request(reply)
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


async def map_words(words: str, *, timeout: float = GEMINI_TIMEOUT) -> Mapped | None:
    """(intent, name), a Request, or None when Gemini says it isn't one; raises
    IntentUnavailable."""
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
