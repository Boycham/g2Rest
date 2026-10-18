"""Draft orders and the code guards behind the agent tools (CONTRACT.md §5).

The agent proposes; this module decides. Every tool returns a JSON-able dict and never
raises: errors go back to the agent as results. Confirm and cancel only *propose*; the
server's tap on the glasses (order.confirm / order.cancel_confirm) does the real thing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from app.data import Dish, Menu, norm

MAX_QTY = 20
MAX_SEAT = 50
OrderStatus = Literal["draft", "fired", "cancelled"]
TOOL_NAMES = (
    "add_item",
    "remove_item",
    "modify_item",
    "set_allergy",
    "confirm_order",
    "cancel_order",
)


class ToolError(Exception):
    """Bad tool arguments or a rule violation; becomes `{"error": ...}` for the agent."""

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.extra = extra


@dataclass
class Line:
    seat: int
    qty: int
    dish: str
    alterations: list[str] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)

    def wire(self) -> dict[str, Any]:
        return {
            "seat": self.seat,
            "qty": self.qty,
            "dish": self.dish,
            "alterations": list(self.alterations),
            "flagged": list(self.flagged),
        }


@dataclass
class Order:
    id: str
    table: str
    capture_id: str | None = None
    owner: str | None = None
    lines: list[Line] = field(default_factory=list)
    allergies: dict[int, list[str]] = field(default_factory=dict)
    status: OrderStatus = "draft"
    proposal: Literal["confirm", "cancel"] | None = None

    def allergy_wire(self) -> list[dict[str, Any]]:
        by_allergen: dict[str, list[int]] = {}
        for seat, names in sorted(self.allergies.items()):
            for name in names:
                by_allergen.setdefault(name.upper(), []).append(seat)
        return [{"allergen": a, "seats": seats} for a, seats in by_allergen.items()]

    def draft_wire(self) -> dict[str, Any]:
        return {
            "type": "order.draft",
            "orderId": self.id,
            "captureId": self.capture_id or "",
            "table": self.table,
            "lines": [line.wire() for line in self.lines],
            "allergies": self.allergy_wire(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **{k: v for k, v in self.draft_wire().items() if k != "type"},
            "owner": self.owner,
            "status": self.status,
            "proposal": self.proposal,
        }

    def summary(self) -> str:
        parts = []
        for ln in self.lines:
            alts = f" {', '.join(ln.alterations)}" if ln.alterations else ""
            parts.append(f"{ln.qty}x {ln.dish}{alts}")
        return ", ".join(parts) or "nothing"


def _int_arg(p: dict[str, Any], name: str, lo: int, hi: int, default: int | None = None) -> int:
    value = p.get(name, default)
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


def _str_arg(p: dict[str, Any], name: str) -> str:
    value = p.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"missing or empty text argument '{name}'")
    return value.strip()


def _str_list_arg(p: dict[str, Any], name: str) -> list[str]:
    value = p.get(name)
    if value is None or value == "":
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ToolError(f"'{name}' must be a list of text values, got {value!r}")
    return [v.strip() for v in value if v.strip()]


class OrderBook:
    def __init__(self, menu: Menu, tables: set[str]) -> None:
        self.menu = menu
        self.tables = tables
        self.orders: dict[str, Order] = {}

    # ---------- lookups ----------

    def get(self, order_id: str) -> Order | None:
        return self.orders.get(order_id)

    def draft_for(self, table: str) -> Order:
        for order in self.orders.values():
            if order.table == table and order.status == "draft":
                return order
        order = Order(id=f"order-{uuid.uuid4().hex[:6]}", table=table)
        self.orders[order.id] = order
        return order

    def open_draft(self, table: str) -> Order | None:
        return next(
            (o for o in self.orders.values() if o.table == table and o.status == "draft"), None
        )

    # ---------- dispatch ----------

    def dispatch(self, tool: str, params: Any) -> tuple[dict[str, Any], Order | None]:
        """Run one tool. Returns (result, order touched); never raises."""
        if tool not in TOOL_NAMES:
            return {"error": f"unknown tool '{tool}'", "tools": list(TOOL_NAMES)}, None
        if not isinstance(params, dict):
            return {"error": "arguments must be an object"}, None
        order: Order | None = None
        try:
            table = self._table(params)
            order = self.draft_for(table)
            result = getattr(self, f"tool_{tool}")(order, params)
            result.setdefault("status", "ok")
            result["orderId"] = order.id
            result["table"] = table
            return result, order
        except ToolError as e:
            return {"error": str(e), **e.extra}, order
        except Exception as e:  # noqa: BLE001 - a bad call must never end the agent session
            return {"error": f"internal error: {type(e).__name__}: {e}"}, order

    def _table(self, p: dict[str, Any]) -> str:
        raw = p.get("table")
        label = f"T{raw}" if isinstance(raw, int | float) and not isinstance(raw, bool) else raw
        if not isinstance(label, str) or not label.strip():
            raise ToolError("missing required argument 'table'")
        label = label.strip().upper()
        if label not in self.tables:
            raise ToolError(f"unknown table {label!r}", tables=sorted(self.tables))
        return label

    def _dish(self, p: dict[str, Any]) -> Dish:
        name = _str_arg(p, "dish")
        dish = self.menu.find(name)
        if dish is None:
            close = self.menu.closest(name)
            raise ToolError(
                f"'{name}' is not on the menu. Did you mean: {', '.join(close)}?", didYouMean=close
            )
        return dish

    def _split(self, dish: Dish, requested: list[str]) -> tuple[list[str], list[str]]:
        allowed = {norm(a): a for a in dish.allowed_alterations}
        ok, flagged = [], []
        for alt in requested:
            match = allowed.get(norm(alt))
            (ok if match else flagged).append(match or alt)
        return ok, flagged

    def _flag_note(self, dish: Dish, flagged: list[str]) -> dict[str, Any]:
        if not flagged:
            return {"flagged": []}
        return {
            "flagged": flagged,
            "warning": f"not allowed for {dish.name}; flagged for the server and NOT applied. "
            f"Allowed: {', '.join(dish.allowed_alterations) or 'none'}",
        }

    def _conflicts(self, order: Order, seat: int) -> list[str]:
        allergies = set(order.allergies.get(seat, []))
        out = []
        for line in order.lines:
            if line.seat != seat:
                continue
            hits = set(self.menu.dishes[line.dish].allergens) & allergies
            out += [f"{line.dish} contains {a}" for a in sorted(hits)]
        return out

    # ---------- tools ----------

    def tool_add_item(self, order: Order, p: dict[str, Any]) -> dict[str, Any]:
        seat = _int_arg(p, "seat", 1, MAX_SEAT)
        dish = self._dish(p)
        qty = _int_arg(p, "qty", 1, MAX_QTY, default=1)
        ok, flagged = self._split(dish, _str_list_arg(p, "alterations"))
        line = Line(seat, qty, dish.name, ok, flagged)
        order.lines.append(line)
        result: dict[str, Any] = {"line": line.wire(), **self._flag_note(dish, flagged)}
        if conflicts := self._conflicts(order, seat):
            result["allergyConflicts"] = conflicts
        return result

    def tool_remove_item(self, order: Order, p: dict[str, Any]) -> dict[str, Any]:
        seat = _int_arg(p, "seat", 1, MAX_SEAT)
        dish = self._dish(p)
        before = len(order.lines)
        order.lines = [ln for ln in order.lines if not (ln.seat == seat and ln.dish == dish.name)]
        if len(order.lines) == before:
            return {
                "status": "not_found",
                "note": f"seat {seat} has no {dish.name}; nothing removed",
            }
        return {"removed": dish.name, "seat": seat}

    def tool_modify_item(self, order: Order, p: dict[str, Any]) -> dict[str, Any]:
        seat = _int_arg(p, "seat", 1, MAX_SEAT)
        dish = self._dish(p)
        change = _str_arg(p, "change")
        lines = [ln for ln in order.lines if ln.seat == seat and ln.dish == dish.name]
        if not lines:
            raise ToolError(f"seat {seat} has no {dish.name}; add it first")
        ok, flagged = self._split(dish, [change])
        for line in lines:
            line.alterations += [a for a in ok if a not in line.alterations]
            line.flagged += [a for a in flagged if a not in line.flagged]
        return {"dish": dish.name, "seat": seat, "applied": ok, **self._flag_note(dish, flagged)}

    def tool_set_allergy(self, order: Order, p: dict[str, Any]) -> dict[str, Any]:
        seat = _int_arg(p, "seat", 1, MAX_SEAT)
        allergen = norm(_str_arg(p, "allergen"))
        seat_allergies = order.allergies.setdefault(seat, [])
        if allergen not in seat_allergies:
            seat_allergies.append(allergen)
        return {
            "seat": seat,
            "allergies": list(seat_allergies),
            "allergyConflicts": self._conflicts(order, seat),
        }

    def tool_confirm_order(self, order: Order, p: dict[str, Any]) -> dict[str, Any]:
        if not order.lines:
            raise ToolError("the order is empty; add items before sending it")
        order.proposal = "confirm"
        return {
            "status": "needs_confirmation",
            "action": "confirm",
            "readback": f"Send {order.table}: {order.summary()}?",
            "note": "the server must tap on the glasses to send it; it is NOT sent yet",
        }

    def tool_cancel_order(self, order: Order, p: dict[str, Any]) -> dict[str, Any]:
        targets = [self._dish({"dish": raw}).name for raw in _str_list_arg(p, "items")]
        order.proposal = "cancel"
        what = ", ".join(targets) or "the whole order"
        return {
            "status": "needs_confirmation",
            "action": "cancel",
            "items": targets,
            "readback": f"Cancel {what} for {order.table}?",
            "note": "the server must tap on the glasses to cancel; nothing is cancelled yet",
        }

    # ---------- the tap ----------

    def fire(self, order_id: str) -> Order:
        order = self._draft(order_id)
        order.status = "fired"
        order.proposal = None
        return order

    def cancel(self, order_id: str) -> Order:
        order = self._draft(order_id)
        order.status = "cancelled"
        order.proposal = None
        return order

    def _draft(self, order_id: str) -> Order:
        order = self.orders.get(order_id)
        if order is None:
            raise ToolError(f"unknown order {order_id!r}")
        if order.status != "draft":
            raise ToolError(f"order {order_id} is already {order.status}")
        return order
