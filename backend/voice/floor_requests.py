"""Floor requests and table statuses said aloud: "table 2 wants the check", "T4 needs bread",
"six needs more water", "clear table three", "T5 is ready to order", "table five is free".

A pattern parser, no LLM. A request needs a table reference ("table N", "TN", or in voice a
bare number first) next to a request phrase, so table talk ("a table for two") and orders
("table two, the salmon") never match. The relay only proposes; a tap on the glasses creates
the task or sets the status (code decides, never the agent).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from commands import HOMOPHONES, TABLE_FILLERS, number_of, words

TASK_KINDS = ("CHECK", "RUN", "CLEAR", "ORDER")
# backend/app/data.py TABLE_STATUSES
STATUSES = ("empty", "seated", "ordered", "waiting", "eating", "check")
# The status word a server says -> the model's status ("paid": the party left, the table's free).
STATUS_WORDS = {
    "free": "empty", "empty": "empty", "open": "empty", "available": "empty", "paid": "empty",
    "left": "empty", "gone": "empty", "seated": "seated", "sat": "seated", "ordered": "ordered",
    "waiting": "waiting", "eating": "eating", "check": "check", "bill": "check",
}  # fmt: skip
# A table whose status implies work gets that task too (backend dedupes an open one).
STATUS_TASK = {"check": "CHECK"}
REQUEST_VERBS = {
    "wants": 1, "want": 1, "needs": 1, "need": 1, "wanted": 1, "needed": 1, "requests": 1,
    "would like": 2, "d like": 2, "could use": 2, "asked for": 2, "asks for": 2,
    "asking for": 2, "is asking for": 3,
}  # fmt: skip
LEAD_FILLERS = frozenset({"s", "is", "are", "just", "now", "already", "finally", "all", "also"})
OBJECT_FILLERS = frozenset(
    {"the", "a", "an", "some", "more", "another", "their", "its", "his", "her", "them", "us",
     "of", "extra", "few", "couple", "new", "fresh", "please", "now"}
)  # fmt: skip
CHECK_WORDS = frozenset({"check", "cheque", "bill", "checks"})
CLEAR_WORDS = frozenset({"clearing", "cleared", "clear", "bussing", "bussed", "bused", "reset"})
CLEAR_VERBS = frozenset({"clear", "bus", "reset"})
FOOD_WORDS = frozenset({"food", "mains", "entrees", "apps", "appetizers", "plates", "dessert"})
# "T4 needs a minute" is not something to run.
NOT_RUN = frozenset({"minute", "moment", "second", "time", "help", "you", "me", "to", "it"})
MAX_NOTE_WORDS = 3
# The note ends at the next clause ("T4 needs bread and the check", "bread, thanks").
NOTE_STOP = frozenset({"and", "please", "thanks", "thank", "anything", "but", "so", "then"})
MAX_PREDICATE_WORDS = 8


@dataclass(frozen=True)
class Request:
    table: int
    kind: str | None = None  # a task to create (TASK_KINDS)
    status: str | None = None  # a table status to set (STATUSES)
    vip: bool = False  # "T4 VIP seated"
    note: str | None = None  # "bread", "paid", "on mains"

    def wire(self) -> dict[str, object]:
        out: dict[str, object] = {"table": f"T{self.table}"}
        if self.kind:
            out["kind"] = self.kind
        if self.status:
            out["status"] = self.status
        if self.vip:
            out["vip"] = True
        if self.note:
            out["note"] = self.note
        return out


def _table_ref(ws: list[str], i: int, strict: bool) -> tuple[int | None, int]:
    """A table reference starting at ws[i] ("table 2", "table number two", "t4", "t 4") and
    how many words it took. `strict` skips homophones ("a table for two")."""
    w = ws[i]
    if re.fullmatch(r"t\d{1,3}", w):
        return number_of(w[1:]), 1
    if w in ("t", "table", "tables") and i + 1 < len(ws):
        skip = 1 if w != "t" and ws[i + 1] in TABLE_FILLERS and i + 2 < len(ws) else 0
        nw = ws[i + 1 + skip]
        if strict and nw in HOMOPHONES:
            return None, 0
        n = number_of(nw)
        return (n, 2 + skip) if n is not None else (None, 0)
    return None, 0


def _is_verb(rest: list[str]) -> int:
    for phrase, width in REQUEST_VERBS.items():
        if rest[:width] == phrase.split():
            return width
    return 0


def _predicate(
    rest: list[str], table: int, statuses: bool, is_dish: Callable[[str], bool]
) -> Request | None:
    """What follows a table reference: "wants the check", "needs bread", "is ready to order",
    "is free" (statuses only by voice)."""
    rest = rest[:MAX_PREDICATE_WORDS]
    while rest and rest[0] in LEAD_FILLERS:
        rest = rest[1:]
    if not rest:
        return None
    w = rest[0]
    if w == "ready":
        nxt = [x for x in rest[1:4] if x not in ("to", "for", "the", "their")]
        if nxt[:1] in (["order"], ["orders"], ["ordering"]):
            return Request(table, kind="ORDER")
        if nxt[:1] and nxt[0] in CHECK_WORDS:
            return Request(table, kind="CHECK", status="check")
        return None
    if width := _is_verb(rest):
        obj = rest[width:]
        if obj[:2] == ["to", "order"]:
            return Request(table, kind="ORDER")
        if obj[:2] in (["to", "pay"], ["to", "be"]):
            obj = obj[1:] if obj[1] == "pay" else obj[2:]
            if obj[:1] == ["pay"]:
                return Request(table, kind="CHECK", status="check")
        obj = [x for x in obj if x not in OBJECT_FILLERS]
        if not obj or obj[0] in NOT_RUN:
            return None
        if obj[0] in CHECK_WORDS:
            return Request(table, kind="CHECK", status="check")
        if obj[0] in CLEAR_WORDS:
            return Request(table, kind="CLEAR")
        cut = next((k for k, x in enumerate(obj) if x in NOTE_STOP), len(obj))
        note = obj[: min(cut, MAX_NOTE_WORDS)]
        if not note:
            return None
        if any(is_dish(" ".join(note[:k])) for k in range(len(note), 0, -1)):
            return None  # "table two wants the salmon" is an order, not a run
        return Request(table, kind="RUN", note=" ".join(note))
    if w in ("dirty", "messy") or (w == "to" and any(x in CLEAR_WORDS for x in rest[1:3])):
        return Request(table, kind="CLEAR")
    if not statuses:
        return None
    if w == "vip" and rest[1:2] and rest[1] in ("seated", "sat"):
        return Request(table, status="seated", vip=True)
    if w in ("has", "have", "got") and rest[1:]:
        if [x for x in rest[1:3] if x not in OBJECT_FILLERS][:1] in ([f] for f in FOOD_WORDS):
            return Request(table, status="eating")
        if rest[1] in ("paid", "left", "ordered", "sat"):
            rest, w = rest[1:], rest[1]
    status = STATUS_WORDS.get(w)
    if status is None:
        return None
    vip = status == "seated" and "vip" in rest[1:3]
    note = "paid" if w == "paid" else None
    if status == "waiting" and rest[1:2] and rest[1] in ("on", "for"):
        note = " ".join(rest[1:3])
    return Request(table, kind=STATUS_TASK.get(status), status=status, vip=vip, note=note)


def _never_dish(_: str) -> bool:
    return False


def parse_request(
    text_or_words: str | list[str],
    *,
    voice: bool = False,
    is_dish: Callable[[str], bool] = _never_dish,
) -> Request | None:
    """The first request in one clause. `voice` (the words after "verity"): a bare number
    may open it ("six needs water"), homophones count after "table", and statuses count."""
    ws = words(text_or_words) if isinstance(text_or_words, str) else text_or_words
    for i, w in enumerate(ws):
        if w in CLEAR_VERBS and i + 1 < len(ws):
            k = i + 2 if ws[i + 1] in ("off", "down") and i + 2 < len(ws) else i + 1
            n, _ = _table_ref(ws, k, strict=not voice)
            if n is not None:
                return Request(n, kind="CLEAR")
        n, used = _table_ref(ws, i, strict=not voice)
        if n is None and i == 0 and (voice or w not in HOMOPHONES):
            n, used = number_of(w), 1
        if n is None:
            continue
        if req := _predicate(ws[i + used :], n, statuses=voice, is_dish=is_dish):
            return req
        if voice:
            return None
    return None


def requests_in(text: str, is_dish: Callable[[str], bool] = _never_dish) -> list[Request]:
    """Every request said in a clip's transcript, one per table and kind, in order."""
    out: list[Request] = []
    for part in re.split(r"[.?!;]+", text):
        for clause in part.split(","):
            req = parse_request(clause, is_dish=is_dish)
            if req and not any((r.table, r.kind) == (req.table, req.kind) for r in out):
                out.append(req)
    return out
