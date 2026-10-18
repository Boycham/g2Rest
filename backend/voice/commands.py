"""Voice commands: the wake word "verity" followed by one fixed command word. No LLM here.

Only a command word directly after the wake word counts, so guest conversation ("we're done
here", "accept my apology") never triggers anything. Spellings come from the noise test in
NOTES.md; add a variant only when the test shows Scribe needs it. Other short words after the
wake word come back as `unknown` for `gemini_intent` to map onto one of these intents.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from floor_requests import Request

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
    # "verity ramp" shows the card's dishes; "verity ramp on/off" turns the RUN-card hint on or off.
    "ramp": "ramp",
    # Scribe writes the TTS "verity queue" as "Verity Q" (2/2 in the simulator run).
    "q": "queue",
    "cue": "queue",
}
INTENTS = tuple(dict.fromkeys(COMMANDS.values()))
# Scribe writes "hand off" / "hand-off" / "never mind" as two words.
BIGRAMS = {("hand", "off"): "handoff", ("never", "mind"): "nevermind"}
# Words after "verity" in the same sentence that are kept for Gemini; longer runs are talk.
MAX_UNKNOWN_WORDS = 5
# "Verity is my sister's name": a sentence about someone called Verity, not a command, so it
# isn't sent to Gemini (realtime Scribe commits it as its own segment once the gate is on).
ABOUT_VERITY = frozenset({"is", "was", "s", "has", "had", "said", "says", "and", "who", "will"})
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
RAMP_TOGGLES = frozenset({"on", "off"})


@dataclass(frozen=True)
class Command:
    intent: str  # one of INTENTS, or "unknown"
    name: str | None = None  # handoff target
    table: int | None = None  # "verity table 4"; None if no number followed
    words: str | None = None  # the unmatched words, for "unknown"
    toggle: str | None = None  # "verity ramp on/off": "on" or "off"; None opens the ramp view
    request: Request | None = None  # "verity table 2 wants the check" (intent "request")


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


# Sound-alikes: misheard spellings accepted only right after a wake-word match. Each entry
# says why; add one only when the noise test or a real run shows Scribe writing it.
WAKE_SOUNDALIKES = {
    "verily": "near-identical vowels; 'Verily' is a real word Scribe can prefer",
    "variety": "the same three stressed syllables under babble",
    "verety": "one-letter slip of the name",
    "varity": "one-letter slip of the name",
}
# Close to "verity" but common words that must never wake anything.
NOT_WAKE = frozenset({"verify", "very", "rarity", "clarity", "charity", "parity", "purity"})
SOUNDALIKES = {
    "except": ("accept", "same stress and consonants; common Scribe swap"),
    "conform": ("confirm", "one vowel apart"),
    "click": ("clip", "same onset, only the final stop differs"),
    "clear": ("clip", "how Scribe wrote 'verity, clip' in 4/4 babble runs at -6 and -3 dB"),
    "dunne": ("done", "surname spelling, like 'Dunn' (realtime Scribe)"),
    "queued": ("queue", "inflection Scribe writes after the name"),
}
# Edit distance 1 is allowed after an exact "verity" for these longer words only; short ones
# (up, down, back, done, clip, menu, queue) have too many one-letter neighbours.
FUZZY_MIN_LEN = 5


def _within_one_edit(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1 or a == b:
        return a == b
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i + (len(a) == len(b)) :] == b[i + 1 :]


def is_wake_soundalike(word: str) -> bool:
    return word not in NOT_WAKE and (word in WAKE_SOUNDALIKES or _within_one_edit(word, "verity"))


def soundalike_of(word: str, exact_wake: bool) -> str | None:
    if word in SOUNDALIKES:
        return SOUNDALIKES[word][0]
    if not exact_wake or len(word) < FUZZY_MIN_LEN:
        return None
    for cmd, intent in COMMANDS.items():
        if len(cmd) >= FUZZY_MIN_LEN and _within_one_edit(word, cmd):
            return intent
    return None


def _clauses(text: str) -> list[tuple[list[str], frozenset[int]]]:
    """Sentences as words, with the indices where a clause starts (after a comma too)."""
    out = []
    for part in re.split(r"[.?!;]+", text):
        ws: list[str] = []
        starts = set()
        for clause in part.split(","):
            starts.add(len(ws))
            ws += words(clause)
        if ws:
            out.append((ws, frozenset(starts)))
    return out


def parse_commands(text: str, soundalikes: bool = True) -> list[Command]:
    """Every command in `text` that directly follows the wake word, in order.

    "verity handoff Maya" carries the name; "verity <other words>" (at most
    MAX_UNKNOWN_WORDS, same sentence) is `unknown` so the caller can ask Gemini.
    With `soundalikes`, a misheard wake word (WAKE_SOUNDALIKES, or one edit from "verity")
    counts only at the start of a sentence or clause and only before a command word, never
    an unknown; the word after the wake word may be a SOUNDALIKES entry, or (after an exact
    "verity") one edit from a longer command word.
    """
    out: list[Command] = []
    for ws, starts in _clauses(text):
        i = 0
        while i < len(ws):
            step = 1 if ws[i] in WAKE_WORDS else 2 if tuple(ws[i : i + 2]) in WAKE_BIGRAMS else 0
            exact = bool(step)
            if not step and soundalikes and i in starts and is_wake_soundalike(ws[i]):
                step = 1
            if not step or i + step >= len(ws):
                i += 1
                continue
            j = i + step
            if exact and (req := _request_after(ws[j:])):
                out.append(Command("request", request=req[0]))
                i = j + req[1]
                continue
            if (intent := BIGRAMS.get(tuple(ws[j : j + 2]))) is not None:
                width = 2
            else:
                intent, width = command_of(ws[j]), 1
                if intent is None and soundalikes:
                    intent = soundalike_of(ws[j], exact)
            if intent is None and not exact:
                i += 1
                continue
            if intent is None and ws[j] in ABOUT_VERITY:
                i = j
                continue
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
            if intent == "ramp" and j + 1 < len(ws) and ws[j + 1] in RAMP_TOGGLES:
                out.append(Command("ramp", toggle=ws[j + 1]))
                i = j + 2
                continue
            if intent == "handoff":
                name = _name_after(ws[j + width : j + width + 2])
                width += 2 if name and ws[j + width] in NAME_FILLERS else 1 if name else 0
            out.append(Command(intent, name=name))
            i = j + width
    return out


def _request_after(rest: list[str]) -> tuple[Request, int] | None:
    """ "verity table 2 wants the check" / "verity T4 needs bread" / "verity table five is
    free": a floor request or table status, before the command words (so "clear table three"
    isn't a clip and "table 2 ..." isn't set-table). A bare "table N" stays set-table."""
    from floor_requests import parse_request

    nxt = next((k for k in range(len(rest)) if rest[k] in WAKE_WORDS), len(rest))
    req = parse_request(rest[:nxt], voice=True)
    return (req, nxt) if req else None


def find_commands(text: str) -> list[str]:
    """The fixed-list intents in `text` (no unknowns), in order."""
    return [c.intent for c in parse_commands(text) if c.intent != "unknown"]


DATA = Path(__file__).resolve().parents[2] / "data"
# Realtime Scribe takes at most 50 keyterms of at most 20 characters (checked live: a longer
# one is refused with invalid_request); batch takes 1000 of < 50 characters.
REALTIME_KEYTERMS, REALTIME_KEYTERM_CHARS = 50, 20
KEYTERM_COMMANDS = (
    "up", "down", "back", "confirm", "clip", "accept", "decline", "done", "handoff",
    "nevermind", "revert", "menu", "queue", "table", "ramp", "exit",
)  # fmt: skip
# Floor requests and table statuses (floor_requests.py); the rest are plain words Scribe gets.
KEYTERM_REQUESTS = ("check", "bill", "bread", "water", "refill", "seated", "free", "paid")
KEYTERM_NUMBERS = ("one", "two", "three", "four", "five", "six", "seven", "eight")


def keyterms(realtime: bool = True, data: Path = DATA) -> list[str]:
    """Scribe biasing terms: the wake word, every command word, staff names, the numbers one
    to eight and the dish names (realtime: a dish name over 20 characters uses its first
    alias; batch: names and all aliases)."""
    floor = json.loads((data / "floor.json").read_text())
    menu = json.loads((data / "menu.json").read_text())["dishes"]
    staff = [p["name"] for p in [*floor.get("servers", []), floor.get("manager") or {}] if p]
    dishes: list[str] = []
    for d in menu:
        names = [d["name"], *d.get("aliases", [])]
        if realtime:
            names = [n for n in names if len(n) <= REALTIME_KEYTERM_CHARS][:1]
        dishes += names
    terms = ["Verity", *KEYTERM_COMMANDS, *KEYTERM_REQUESTS, *staff, *KEYTERM_NUMBERS, *dishes]
    out = list(dict.fromkeys(t for t in terms if t))
    return out[:REALTIME_KEYTERMS] if realtime else out
