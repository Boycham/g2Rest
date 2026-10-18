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

MENU_PATH = Path(__file__).with_name("menu.json")
COURSES = ("appetizer", "main", "dessert")
MAX_QTY = 20


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

    def __init__(self, menu: Menu):
        self.menu = menu
        self.tables: dict[int, Table] = {}
        self.current_table: int | None = None
        self._next_proposal = 1

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
    "add_item",
    "remove_item",
    "modify_item",
    "set_allergy",
    "confirm_order",
    "cancel_order",
)
