"""Voice commands: the wake word "verity" followed by one fixed command word. No LLM.

Only a command word directly after the wake word counts, so guest conversation ("we're done
here", "accept my apology") never triggers anything. Spellings come from the noise test in
NOTES.md; add a variant only when the test shows Scribe needs it.
"""

from __future__ import annotations

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
}
INTENTS = tuple(COMMANDS.values())


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


def find_commands(text: str) -> list[str]:
    """Every intent in `text` that directly follows the wake word, in order."""
    ws = words(text)
    out: list[str] = []
    i = 0
    while i < len(ws):
        step = 1 if ws[i] in WAKE_WORDS else 2 if tuple(ws[i : i + 2]) in WAKE_BIGRAMS else 0
        intent = command_of(ws[i + step]) if step and i + step < len(ws) else None
        if intent:
            out.append(intent)
            i += step + 1
            continue
        i += 1
    return out
