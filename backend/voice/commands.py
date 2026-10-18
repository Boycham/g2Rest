"""Voice commands: the wake word "verity" followed by one fixed command word. No LLM here.

Only a command word directly after the wake word counts, so guest conversation ("we're done
here", "accept my apology") never triggers anything. Spellings come from the noise test in
NOTES.md; add a variant only when the test shows Scribe needs it. Other short words after the
wake word come back as `unknown` for `gemini_intent` to map onto one of these intents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

WAKE_WORDS = frozenset({"verity"})
WAKE_BIGRAMS = frozenset[tuple[str, str]]()
COMMANDS = {
    "up": "up",
    "down": "down",
    "back": "back",
    "confirm": "confirm",
    "clip": "clip",
    "accept": "accept",
    "decline": "decline",
    "done": "done",
    "handoff": "handoff",
    "nevermind": "nevermind",
    "revert": "revert",
    "menu": "menu",
    "controls": "menu",
    "queue": "queue",
    # "verity table 4" / "verity table four": binds the unsent draft to that table.
    "table": "table",
    # Scribe writes the TTS "verity queue" as "Verity Q" (2/2 in the simulator run).
    "q": "queue",
    "cue": "queue",
}
INTENTS = tuple(dict.fromkeys(COMMANDS.values()))
# Scribe writes "hand off" / "hand-off" / "never mind" as two words.
BIGRAMS = {("hand", "off"): "handoff", ("never", "mind"): "nevermind"}
# Words after "verity" in the same sentence that are kept for Gemini; longer runs are talk.
MAX_UNKNOWN_WORDS = 5
NAME_FILLERS = frozenset({"to"})
# Table numbers as Scribe writes them: digits, or words (with the homophones "for", "to").
NUMBER_WORDS = {
    w: n
    for n, ws in enumerate(
        (
            (),
            ("one", "won"),
            ("two", "to", "too"),
            ("three",),
            ("four", "for", "fore"),
            ("five",),
            ("six",),
            ("seven",),
            ("eight", "ate"),
            ("nine",),
            ("ten",),
            ("eleven",),
            ("twelve",),
        )
    )
    for w in ws
}
TABLE_FILLERS = frozenset({"number", "no"})


@dataclass(frozen=True)
class Command:
    intent: str  # one of INTENTS, or "unknown"
    name: str | None = None  # handoff target
    table: int | None = None  # "verity table 4"; None if no number followed
    words: str | None = None  # the unmatched words, for "unknown"


def words(text: str) -> list[str]:
    return "".join(c if c.isalnum() else " " for c in text.lower()).split()


# Scribe inflects a clipped command ("Verity accepts", "Verity clipped", "Verity confirmed").
SUFFIXES = ("", "s", "ed", "d")
# Realtime Scribe hears "Verity, done." as "Verity Dunn." (a surname after a first name), 2/2
# times in the noise test; nothing else needed a variant.
INFLECTED = {"clipped": "clip", "dunn": "done", "dun": "done"}


def command_of(word: str) -> str | None:
    if word in INFLECTED:
        return INFLECTED[word]
    for cmd, intent in COMMANDS.items():
        if any(word == cmd + suf for suf in SUFFIXES):
            return intent
    return None


def number_of(word: str) -> int | None:
    if word.isdigit():
        return int(word) if 1 <= int(word) <= 999 else None
    return NUMBER_WORDS.get(word)


HOMOPHONES = frozenset({"won", "to", "too", "for", "fore", "ate"})


def _table_after(rest: list[str], strict: bool = False) -> tuple[int | None, int]:
    """The table number in the words after "table" and how many words it took. `strict`
    skips homophones, so "a table for two" in conversation is not table 4."""
    skip = 1 if rest[:1] and rest[0] in TABLE_FILLERS else 0
    word = rest[skip] if len(rest) > skip else ""
    n = None if strict and word in HOMOPHONES else number_of(word)
    return (n, skip + 1) if n is not None else (None, 0)


def tables_said(text: str) -> list[int]:
    """Every "table N" in a clip's transcript, in order ("that was table four" -> [4])."""
    out: list[int] = []
    for ws in _sentences(text):
        for i, w in enumerate(ws):
            if w == "table" and (n := _table_after(ws[i + 1 : i + 3], strict=True)[0]):
                out.append(n)
    return out


def _sentences(text: str) -> list[list[str]]:
    return [ws for part in re.split(r"[.?!;]+", text) if (ws := words(part))]


def _name_after(rest: list[str]) -> str | None:
    rest = [w for w in rest if w not in NAME_FILLERS][:1]
    return rest[0].capitalize() if rest and rest[0].isalpha() else None


def parse_commands(text: str) -> list[Command]:
    """Every command in `text` that directly follows the wake word, in order.

    "verity handoff Maya" carries the name; "verity <other words>" (at most
    MAX_UNKNOWN_WORDS, same sentence) is `unknown` so the caller can ask Gemini.
    """
    out: list[Command] = []
    for ws in _sentences(text):
        i = 0
        while i < len(ws):
            step = 1 if ws[i] in WAKE_WORDS else 2 if tuple(ws[i : i + 2]) in WAKE_BIGRAMS else 0
            if not step or i + step >= len(ws):
                i += 1
                continue
            j = i + step
            if (intent := BIGRAMS.get(tuple(ws[j : j + 2]))) is not None:
                width = 2
            else:
                intent, width = command_of(ws[j]), 1
            if intent is None:
                rest = ws[j:]
                nxt = next((k for k in range(len(rest)) if rest[k] in WAKE_WORDS), len(rest))
                if nxt <= MAX_UNKNOWN_WORDS:
                    out.append(Command("unknown", words=" ".join(rest[:nxt])))
                i = j + nxt
                continue
            name = None
            if intent == "table":
                n, used = _table_after(ws[j + 1 : j + 3])
                out.append(Command("table", table=n))
                i = j + 1 + used
                continue
            if intent == "handoff":
                name = _name_after(ws[j + width : j + width + 2])
                width += 2 if name and ws[j + width] in NAME_FILLERS else 1 if name else 0
            out.append(Command(intent, name=name))
            i = j + width
    return out


def find_commands(text: str) -> list[str]:
    """The fixed-list intents in `text` (no unknowns), in order."""
    return [c.intent for c in parse_commands(text) if c.intent != "unknown"]
