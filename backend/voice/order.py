"""In-memory order model and the code guards for every agent tool call.

The agent proposes; this module decides. Every tool returns a JSON-able dict and
never raises: errors go back to the agent as results.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MENU_PATH = Path(__file__).resolve().parents[2] / "data" / "menu.json"  # one menu for both lanes
FLOOR_PATH = MENU_PATH.with_name("floor.json")
# Who gave the draft its table, weakest first: said in a clip, the ORDER task, "verity table N".
TABLE_SOURCES = ("spoken", "task", "voice")
KEPT_FROM = {"task": "the ORDER task", "voice": "verity table"}


def floor_tables(path: Path = FLOOR_PATH) -> frozenset[int]:
    """Table numbers on the floor plan ("T4" -> 4)."""
    tables = json.loads(path.read_text())["tables"]
    return frozenset(int(t["id"].removeprefix("T")) for t in tables)


COURSES = ("appetizer", "main", "dessert")
MAX_QTY = 20
UNKNOWN_TABLE = 0  # the draft's key until a table is known (ORDER task or spoken)
MAX_UNCERTAIN = 3
MAX_NOTES = 3
MAX_LINE_CHARS = 48
# The G2 has no speaker and the agent's replies are never shown: anything shown must be a
# statement for the server to glance at, never a question to answer.
QUESTION_STARTS = (
    "what", "which", "who", "how", "can", "could", "would", "should", "do ", "does", "did",
    "is ", "are ", "will", "please", "ask", "confirm", "clarify", "check with",
)  # fmt: skip


class ToolError(Exception):
    """Bad tool arguments; reported back to the agent, never raised past dispatch."""


def _norm(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").split())


@dataclass(frozen=True)
class Dish:
    name: str
    course: str
    temperature: str
    allergens: tuple[str, ...]
    allowed_alterations: tuple[str, ...]
    aliases: tuple[str, ...] = ()


class Menu:
    def __init__(self, dishes: list[Dish]):
        self.dishes = {d.name: d for d in dishes}
        self._lookup: dict[str, Dish] = {}
        for d in dishes:
            for key in (d.name, *d.aliases):
                self._lookup[_norm(key)] = d

    @classmethod
    def load(cls, path: Path = MENU_PATH) -> Menu:
        raw = json.loads(path.read_text())
        return cls(
            [
                Dish(
                    name=d["name"],
                    course=d["course"],
                    temperature=d["temperature"],
                    allergens=tuple(d["allergens"]),
                    allowed_alterations=tuple(d["allowed_alterations"]),
                    aliases=tuple(d.get("aliases", [])),
                )
                for d in raw["dishes"]
            ]
        )

    def resolve(self, name: str) -> Dish:
        """Exact name or alias (case/hyphen-insensitive, leading 'the' ignored)."""
        key = _norm(name)
        key = key.removeprefix("the ")
        dish = self._lookup.get(key)
        if dish is None:
            raise ToolError(
                f"'{name}' is not on the menu. Did you mean: {', '.join(self.closest(name))}?"
            )
        return dish

    def closest(self, name: str, n: int = 3) -> list[str]:
        key = _norm(name)
        scored: dict[str, float] = {}
        for alias, dish in self._lookup.items():
            score = difflib.SequenceMatcher(None, key, alias).ratio()
            if any(w in alias.split() for w in key.split()):
                score += 0.3
            scored[dish.name] = max(scored.get(dish.name, 0.0), score)
        return sorted(scored, key=lambda k: -scored[k])[:n]

    def prompt_text(self) -> str:
        lines = []
        for d in self.dishes.values():
            lines.append(
                f"- {d.name} ({d.course}, {d.temperature}); allergens: "
                f"{', '.join(d.allergens) or 'none'}; allowed alterations: "
                f"{', '.join(d.allowed_alterations) or 'none'}"
            )
        return "\n".join(lines)


@dataclass
class Item:
    dish: str
    qty: int
    alterations: list[str] = field(default_factory=list)
    flagged_alterations: list[str] = field(default_factory=list)


@dataclass
class Seat:
    items: list[Item] = field(default_factory=list)
    allergies: list[str] = field(default_factory=list)


@dataclass
class Table:
    seats: dict[int, Seat] = field(default_factory=dict)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    status: str = "draft"  # draft -> sent | cancelled, only through a tap (accept/confirm)
    notes: list[str] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)
    summary: str = ""
    answers: list[dict[str, Any]] = field(default_factory=list)

    def seat(self, n: int) -> Seat:
        return self.seats.setdefault(n, Seat())


def _int_arg(
    params: dict[str, Any], name: str, lo: int, hi: int, default: int | None = None
) -> int:
    value = params.get(name, default)
    if value is None:
        raise ToolError(f"missing required argument '{name}'")
    if isinstance(value, bool):
        raise ToolError(f"'{name}' must be a whole number, got {value!r}")
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        raise ToolError(f"'{name}' must be a whole number, got {value!r}") from None
    if not as_float.is_integer() or not lo <= as_float <= hi:
        raise ToolError(f"'{name}' must be a whole number from {lo} to {hi}, got {value!r}")
    return int(as_float)


def _str_arg(params: dict[str, Any], name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"missing or empty text argument '{name}'")
    return value.strip()


FILLER_WORDS = frozenset({"no", "the", "on", "a", "an", "of", "with", "extra", "side"})


def _words(text: str) -> list[str]:
    return "".join(c if c.isalnum() else " " for c in text.lower()).split()


def is_question(text: str) -> bool:
    t = _norm(text).lstrip("?'\" ")
    return text.rstrip().endswith("?") or t.startswith(QUESTION_STARTS)


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_LINE_CHARS else text[: MAX_LINE_CHARS - 1] + "…"


def _list_of_objects(params: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = params.get(name)
    if value is None or value == "":
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise ToolError(f"'{name}' must be a list of objects, got {value!r}")
    return value


def _str_list_arg(params: dict[str, Any], name: str) -> list[str]:
    value = params.get(name)
    if value is None or value == "":
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ToolError(f"'{name}' must be a list of text values, got {value!r}")
    return [v.strip() for v in value if v.strip()]


class OrderBook:
    """Additions apply live. Removals, cancels and confirms only become pending proposals;
    `accept` (a tap on the glasses) applies one and `reject` (swipe up) drops it."""

    def __init__(self, menu: Menu, floor: frozenset[int] | None = None):
        self.menu = menu
        self.floor = floor  # None: any table 1-999 (tests, run_spike)
        self.tables: dict[int, Table] = {}
        self.current_table: int | None = None
        self.table_source: str | None = None  # one of TABLE_SOURCES; a stronger one wins
        # Words of the clip the agent is reading; set_order only keeps what was said.
        self.heard: set[str] | None = None
        # The last set_order's guest entries, so set_talk numbers guests the same way.
        self.clip_entries: list[dict[str, Any]] = []
        self._next_proposal = 1
        self.out: set[str] = set()  # 86'd dish names, from the backend's menu.86 frame

    def hear(self, transcript: str) -> None:
        """A new clip's transcript; its summary and answers replace the last clip's."""
        self.heard = set(_words(transcript))
        if table := self.tables.get(self.draft_table):
            table.summary, table.answers = "", []

    def was_said(self, phrase: str) -> bool:
        """True if every content word of `phrase` is in the clip (or no clip is set)."""
        if self.heard is None:
            return True
        words = [w for w in _words(phrase) if w not in FILLER_WORDS]
        return all(w in self.heard or w.rstrip("s") in self.heard for w in words)

    def dish_said(self, dish: Dish) -> bool:
        return any(self.was_said(k) for k in (dish.name, *dish.aliases))

    @property
    def draft_table(self) -> int:
        return self.current_table if self.current_table is not None else UNKNOWN_TABLE

    def bind_table(self, n: int, source: str) -> None:
        """Give the draft its table. A table said in a clip can't override the ORDER task's
        (a bystander may name another table); "verity table N" overrides both. Only an
        unsent draft can change. Raises ToolError if refused."""
        if not 1 <= n <= 999:
            raise ToolError(f"table must be 1 to 999, got {n}")
        if self.floor is not None and n not in self.floor:
            raise ToolError(f"no table {n}")
        cur = self.draft_table
        held = self.table_source
        weaker = held is not None and TABLE_SOURCES.index(source) < TABLE_SOURCES.index(held)
        if weaker and n != cur:
            raise ToolError(f"heard table {n}, kept table {cur} from {KEPT_FROM[held]}")
        mine = self.tables.get(cur)
        if mine is not None and mine.status != "draft":
            raise ToolError(f"already {mine.status}")
        existing = self.tables.get(n)
        if n != cur and existing is not None and existing.status != "draft":
            raise ToolError(f"table {n}'s order was already {existing.status}")
        if n != cur and cur in self.tables:
            self.tables[n] = self.tables.pop(cur)
        self.current_table = n
        if not weaker:
            self.table_source = source

    def dispatch(self, tool: str, params: Any) -> tuple[dict[str, Any], bool]:
        """Run one tool call. Returns (result, is_error); never raises."""
        handler = getattr(self, f"tool_{tool}", None) if tool in TOOL_NAMES else None
        if handler is None:
            return {"error": f"unknown tool '{tool}'", "tools": list(TOOL_NAMES)}, True
        if not isinstance(params, dict):
            return {"error": "arguments must be an object"}, True
        try:
            return handler(params), False
        except ToolError as e:
            return {"error": str(e)}, True
        except Exception as e:  # noqa: BLE001 - a bad call must never end the session
            return {"error": f"internal error: {type(e).__name__}: {e}"}, True

    def _table(self, params: dict[str, Any]) -> tuple[int, Table]:
        n = _int_arg(params, "table", 1, 999)
        table = self.tables.setdefault(n, Table())
        if table.status != "draft":
            raise ToolError(f"table {n}'s order was already {table.status}; it can't change")
        self.current_table = n
        return n, table

    def _propose(self, table: Table, proposal: dict[str, Any]) -> dict[str, Any]:
        for existing in table.proposals:
            if {k: v for k, v in existing.items() if k != "id"} == proposal:
                return existing
        proposal = {"id": f"p{self._next_proposal}", **proposal}
        self._next_proposal += 1
        table.proposals.append(proposal)
        return proposal

    def _split_alterations(self, dish: Dish, requested: list[str]) -> tuple[list[str], list[str]]:
        allowed = {_norm(a): a for a in dish.allowed_alterations}
        ok, flagged = [], []
        for alt in requested:
            match = allowed.get(_norm(alt))
            (ok if match else flagged).append(match or alt)
        return ok, flagged

    def _flag_note(self, dish: Dish, flagged: list[str]) -> dict[str, Any]:
        if not flagged:
            return {}
        return {
            "flagged_alterations": flagged,
            "warning": f"not allowed for {dish.name}, flagged for the server and NOT applied. "
            f"Allowed: {', '.join(dish.allowed_alterations)}",
        }

    def _allergy_conflicts(self, seat: Seat) -> list[str]:
        out = []
        for item in seat.items:
            hits = set(self.menu.dishes[item.dish].allergens) & set(seat.allergies)
            out += [f"{item.dish} contains {a}" for a in sorted(hits)]
        return out

    def tool_add_item(self, p: dict[str, Any]) -> dict[str, Any]:
        t, table = self._table(p)
        seat_n = _int_arg(p, "seat", 1, 50)
        dish = self.menu.resolve(_str_arg(p, "dish"))
        if dish.name in self.out:
            table.uncertain.append(_short(f"? s{seat_n} {self._label(dish.name)} 86'd"))
            raise ToolError(f"{dish.name} is 86'd tonight; don't sell it")
        qty = _int_arg(p, "qty", 1, MAX_QTY, default=1)
        ok, flagged = self._split_alterations(dish, _str_list_arg(p, "alterations"))
        seat = table.seat(seat_n)
        seat.items.append(Item(dish.name, qty, ok, flagged))
        result = {
            "status": "ok",
            "table": t,
            "seat": seat_n,
            "added": dish.name,
            "qty": qty,
            "alterations": ok,
            **self._flag_note(dish, flagged),
        }
        if conflicts := self._allergy_conflicts(seat):
            result["allergy_conflicts"] = conflicts
        return result

    def _find(self, seat: Seat, dish: Dish) -> list[Item]:
        return [i for i in seat.items if i.dish == dish.name]

    def tool_remove_item(self, p: dict[str, Any]) -> dict[str, Any]:
        t, table = self._table(p)
        seat_n = _int_arg(p, "seat", 1, 50)
        dish = self.menu.resolve(_str_arg(p, "dish"))
        seat = table.seats.get(seat_n)
        if seat is None or not self._find(seat, dish):
            on_seat = ", ".join(i.dish for i in seat.items) if seat and seat.items else "nothing"
            raise ToolError(
                f"seat {seat_n} has no {dish.name} (it has: {on_seat}); nothing removed. "
                "Do not remove a different dish instead unless the server names it."
            )
        proposal = self._propose(
            table, {"action": "remove", "table": t, "seat": seat_n, "dish": dish.name}
        )
        return {
            "status": "needs_confirmation",
            **proposal,
            "note": "the server must tap on the glasses to remove it; it is NOT removed yet",
        }

    def tool_modify_item(self, p: dict[str, Any]) -> dict[str, Any]:
        t, table = self._table(p)
        seat_n = _int_arg(p, "seat", 1, 50)
        dish = self.menu.resolve(_str_arg(p, "dish"))
        change = _str_arg(p, "change")
        found = self._find(table.seat(seat_n), dish)
        if not found:
            raise ToolError(f"seat {seat_n} has no {dish.name}; add it first")
        ok, flagged = self._split_alterations(dish, [change])
        for item in found:
            item.alterations += [a for a in ok if a not in item.alterations]
            item.flagged_alterations += [a for a in flagged if a not in item.flagged_alterations]
        return {
            "status": "ok",
            "table": t,
            "seat": seat_n,
            "dish": dish.name,
            "applied": ok,
            **self._flag_note(dish, flagged),
        }

    def tool_set_allergy(self, p: dict[str, Any]) -> dict[str, Any]:
        t, table = self._table(p)
        seat_n = _int_arg(p, "seat", 1, 50)
        allergen = _norm(_str_arg(p, "allergen"))
        seat = table.seat(seat_n)
        if allergen not in seat.allergies:
            seat.allergies.append(allergen)
        result = {"status": "ok", "table": t, "seat": seat_n, "allergies": seat.allergies}
        if conflicts := self._allergy_conflicts(seat):
            result["allergy_conflicts"] = conflicts
        return result

    def tool_confirm_order(self, p: dict[str, Any]) -> dict[str, Any]:
        t, table = self._table(p)
        if not any(seat.items for seat in table.seats.values()):
            raise ToolError(f"table {t} has no dishes yet; nothing to send")
        proposal = self._propose(table, {"action": "fire", "table": t})
        return {
            "status": "needs_confirmation",
            **proposal,
            "note": "the server must tap on the glasses to send it; it is NOT sent yet",
        }

    def tool_cancel_order(self, p: dict[str, Any]) -> dict[str, Any]:
        t, table = self._table(p)
        ordered = {i.dish for seat in table.seats.values() for i in seat.items}
        targets = []
        for raw in _str_list_arg(p, "items"):
            key = _norm(raw)
            course = key.rstrip("s") if key.rstrip("s") in COURSES else None
            if course:
                if not any(self.menu.dishes[d].course == course for d in ordered):
                    raise ToolError(f"table {t} has no {course} ordered; nothing to cancel")
                targets.append(f"course:{course}")
                continue
            dish = self.menu.resolve(raw)
            if dish.name not in ordered:
                raise ToolError(f"table {t} has no {dish.name}; nothing to cancel")
            targets.append(dish.name)
        proposal = self._propose(
            table, {"action": "cancel", "table": t, "items": targets or ["whole order"]}
        )
        return {
            "status": "needs_confirmation",
            **proposal,
            "note": "the server must tap on the glasses to cancel; nothing is cancelled yet",
        }

    # ---- conversational capture: the whole order from one clip ----

    def tool_set_order(self, p: dict[str, Any]) -> dict[str, Any]:
        """The complete order heard in a clip. Code numbers the seats, checks every dish and
        alteration, and turns anything already on the draft that the clip drops into a
        removal proposal (a tap applies it), so the agent can only ever add live."""
        notices: list[str] = []
        if p.get("table") not in (None, "", 0):
            try:
                self.bind_table(_int_arg(p, "table", 1, 999), "spoken")
            except ToolError as e:
                notices.append(str(e))
        t = self.draft_table
        table = self.tables.setdefault(t, Table())
        if table.status != "draft":
            raise ToolError(f"table {t}'s order was already {table.status}; it can't change")

        items = _list_of_objects(p, "items")
        allergies = _list_of_objects(p, "allergies")
        unclear = _list_of_objects(p, "unclear")
        seat_of = self._seat_numbers([*items, *allergies, *unclear])
        self.clip_entries = [*items, *allergies, *unclear]

        uncertain: list[str] = []
        flagged: list[str] = []
        held: list[str] = []
        unheard: list[str] = []
        wanted: dict[tuple[int, str], Item] = {}
        unclear_seats = {
            seat_of(u): _norm(str(u.get("text", "")))
            for u in unclear
            if u.get("guest") not in (None, "", 0) or u.get("seat") not in (None, "", 0)
        }
        per_seat: dict[int, int] = {}
        for raw in items:
            per_seat[seat_of(raw)] = per_seat.get(seat_of(raw), 0) + 1
        for raw in items:
            seat = seat_of(raw)
            if seat in unclear_seats and self._guessed(raw, unclear_seats[seat], per_seat[seat]):
                held.append(f"s{seat} {raw.get('dish')}")
                continue
            name = str(raw.get("dish", "")).strip()
            if not name:
                continue
            try:
                dish = self.menu.resolve(name)
            except ToolError:
                close = [self._label(d) for d in self.menu.closest(name, 2)]
                uncertain.append(f"? s{seat} '{name}' not on menu: {' or '.join(close)}")
                continue
            if dish.name in self.out:
                uncertain.append(f"? s{seat} {self._label(dish.name)} 86'd")
                continue
            if not self.dish_said(dish):
                unheard.append(f"s{seat} {dish.name}")
                continue
            qty = _int_arg(raw, "qty", 1, MAX_QTY, default=1)
            asked = _str_list_arg(raw, "alterations")
            unheard += [f"s{seat} {dish.name}: {a}" for a in asked if not self.was_said(a)]
            ok, bad = self._split_alterations(dish, [a for a in asked if self.was_said(a)])
            flagged += [f"s{seat} {dish.name}: {b}" for b in bad]
            item = wanted.setdefault((seat, dish.name), Item(dish.name, 0))
            item.qty = min(MAX_QTY, item.qty + qty)
            item.alterations += [a for a in ok if a not in item.alterations]
            item.flagged_alterations += [a for a in bad if a not in item.flagged_alterations]

        removals = []
        for n, seat in list(table.seats.items()):
            for old in seat.items:
                new = wanted.pop((n, old.dish), None)
                if new is None:
                    proposal = {"action": "remove", "table": t, "seat": n, "dish": old.dish}
                    removals.append(self._propose(table, proposal))
                    continue
                old.qty = new.qty
                old.alterations += [a for a in new.alterations if a not in old.alterations]
                old.flagged_alterations += [
                    a for a in new.flagged_alterations if a not in old.flagged_alterations
                ]
        for (n, _), item in wanted.items():
            table.seat(n).items.append(item)

        for raw in allergies:
            allergen = _norm(str(raw.get("allergen", "")))
            if allergen and not self.was_said(allergen):
                unheard.append(f"allergy {allergen}")
            elif allergen:
                seat = table.seat(seat_of(raw))
                if allergen not in seat.allergies:
                    seat.allergies.append(allergen)

        rejected = []
        for raw in unclear:
            text = str(raw.get("text", "")).strip().lstrip("?").strip()
            text = text.removeprefix("unclear").removeprefix(":").strip()
            if not text:
                continue
            if is_question(text):
                rejected.append(text)
                continue
            seat = f"s{seat_of(raw)} " if raw.get("guest") or raw.get("seat") else ""
            uncertain.append(f"? {seat}{text}")
        table.uncertain = [_short(u) for u in uncertain[:MAX_UNCERTAIN]]
        notes = [n for n in _str_list_arg(p, "notes") if not is_question(n)]
        table.notes = [_short(n) for n in notes[:MAX_NOTES]]
        result: dict[str, Any] = {
            "status": "ok",
            "table": t or None,
            "seats": {
                str(n): [f"{i.qty}x {i.dish}" for i in s.items]
                + [f"allergy {a}" for a in s.allergies]
                for n, s in sorted(table.seats.items())
            },
        }
        if not t:
            result["table_unknown"] = "the server will say the table or an ORDER task sets it"
        if removals:
            result["pending_removals"] = [f"s{r['seat']} {r['dish']}" for r in removals]
            result["note"] = "dropped dishes are NOT removed until the server taps"
        if flagged:
            result["flagged_not_applied"] = flagged
        if unheard:
            result["not_in_clip"] = unheard
            result["warning_unheard"] = "only what was said in the clip is kept"
        if held:
            result["held_unclear"] = held
            result["note_unclear"] = "a guest whose choice is unclear gets no guessed dish"
        if rejected:
            result["rejected_unclear"] = rejected
            result["warning"] = "unclear lines must be statements, never questions"
        if notices:
            result["table_notice"] = notices[0]
        if conflicts := [c for s in table.seats.values() for c in self._allergy_conflicts(s)]:
            result["allergy_conflicts"] = conflicts
        return result

    def tool_set_talk(self, p: dict[str, Any]) -> dict[str, Any]:
        """The clip's summary and the guests' questions, after set_order. Guests keep the
        numbering of that set_order. Code writes every food answer from the menu (answers.py).
        Display only: it never touches the order and works on a sent order too."""
        from answers import answer_all, clean_summary

        table = self.tables.setdefault(self.draft_table, Table())
        questions = _list_of_objects(p, "questions")
        asked_by = [q for q in questions if q.get("guest") or q.get("seat")]
        seat_of = self._seat_numbers([*self.clip_entries, *asked_by])
        table.answers, dropped = answer_all(
            self.menu,
            questions,
            lambda q: seat_of(q) if q.get("guest") or q.get("seat") else None,
            self.was_said,
        )
        table.summary = clean_summary(
            self.menu,
            str(p.get("summary") or ""),
            {a for s in table.seats.values() for a in s.allergies},
            {i.dish for s in table.seats.values() for i in s.items},
        )
        result: dict[str, Any] = {
            "status": "ok",
            "summary": table.summary,
            "answers": [f"{a['q']} -> {a['a']}" for a in table.answers],
            "note": "answers about food are written by code from the menu; reply ok",
        }
        if dropped:
            result["dropped_questions"] = dropped
        return result

    def _guessed(self, raw: dict[str, Any], unclear_text: str, items_for_seat: int) -> bool:
        """A dish for a guest whose choice is marked unclear is a guess unless it is clearly
        something else: it is held if the unclear line names it, or if it is that guest's
        only dish in the clip (the unclear line is their order)."""
        if items_for_seat == 1:
            return True
        try:
            dish = self.menu.resolve(str(raw.get("dish", "")))
        except ToolError:
            return False
        return any(_norm(k) in unclear_text for k in (dish.name, *dish.aliases))

    def _label(self, name: str) -> str:
        dish = self.menu.dishes[name]
        return dish.aliases[0] if dish.aliases else name.lower()

    def _seat_numbers(self, entries: list[dict[str, Any]]) -> Any:
        """Guests are numbered by the agent in the order they first order; code turns them
        into seats: a spoken seat wins, the rest count up from 1 skipping spoken seats."""

        def spoken_seat(e: dict[str, Any]) -> int | None:
            return None if e.get("seat") in (None, "", 0) else _int_arg(e, "seat", 1, 50)

        def guest(e: dict[str, Any]) -> int:
            return _int_arg(e, "guest", 1, 50, default=1)

        spoken = {s for e in entries if (s := spoken_seat(e)) is not None}
        guest_seat: dict[int, int] = {}
        nxt = 1
        for g in sorted({guest(e) for e in entries if spoken_seat(e) is None}):
            while nxt in spoken:
                nxt += 1
            guest_seat[g] = nxt
            nxt += 1

        def seat_of(e: dict[str, Any]) -> int:
            s = spoken_seat(e)
            return s if s is not None else guest_seat[guest(e)]

        return seat_of

    # ---- the server's gestures (never reachable from the agent) ----

    def _pending(self, proposal_id: str) -> tuple[Table, dict[str, Any]]:
        for table in self.tables.values():
            for proposal in table.proposals:
                if proposal["id"] == proposal_id:
                    return table, proposal
        raise ToolError(f"no pending proposal '{proposal_id}'")

    def accept(self, proposal_id: str) -> dict[str, Any]:
        """Apply one pending proposal (the server tapped). Raises ToolError if unknown."""
        table, proposal = self._pending(proposal_id)
        action = proposal["action"]
        if action == "fire" and len(table.proposals) > 1:
            raise ToolError("other changes are still pending; accept or reject them first")
        table.proposals.remove(proposal)
        if action == "remove":
            seat = table.seat(proposal["seat"])
            seat.items = [i for i in seat.items if i.dish != proposal["dish"]]
        elif action == "cancel":
            items = proposal["items"]
            if items == ["whole order"]:
                for seat in table.seats.values():
                    seat.items = []
                table.status = "cancelled"
                table.proposals.clear()
            for seat in table.seats.values():
                seat.items = [i for i in seat.items if not self._cancelled(i, items)]
        elif action == "fire":
            self.fire(proposal["table"])
        return {"status": "applied", **proposal}

    def _cancelled(self, item: Item, targets: list[str]) -> bool:
        course = f"course:{self.menu.dishes[item.dish].course}"
        return item.dish in targets or course in targets

    def reject(self, proposal_id: str) -> dict[str, Any]:
        table, proposal = self._pending(proposal_id)
        table.proposals.remove(proposal)
        return {"status": "rejected", **proposal}

    def fire(self, t: int) -> None:
        """Send the table's order (the server tapped with nothing pending)."""
        if t == UNKNOWN_TABLE:
            raise ToolError("say the table first (TABLE?)")
        table = self.tables.get(t)
        if table is None or not any(seat.items for seat in table.seats.values()):
            raise ToolError(f"table {t} has no dishes to send")
        if table.proposals:
            raise ToolError(f"table {t} still has pending changes; accept or reject them first")
        table.status = "sent"

    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for t, table in sorted(self.tables.items()):
            seats = {
                str(n): {
                    "allergies": s.allergies,
                    "items": [i.__dict__ for i in s.items],
                }
                for n, s in sorted(table.seats.items())
            }
            out[str(t)] = {
                "status": table.status,
                "seats": seats,
                "pending_proposals": table.proposals,
            }
        return out


TOOL_NAMES = (
    "set_order",
    "set_talk",
    "add_item",
    "remove_item",
    "modify_item",
    "set_allergy",
    "confirm_order",
    "cancel_order",
)
