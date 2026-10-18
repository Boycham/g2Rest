from __future__ import annotations

import pytest

from app.data import Floor, Menu
from app.orders import OrderBook, ToolError


@pytest.fixture
def orders(menu: Menu, floor: Floor) -> OrderBook:
    return OrderBook(menu, set(floor.tables))


def test_add_item_resolves_alias_and_builds_draft(orders: OrderBook) -> None:
    result, order = orders.dispatch("add_item", {"table": "T2", "seat": 1, "dish": "halibut"})
    assert result["status"] == "ok" and order is not None
    assert result["line"] == {
        "seat": 1,
        "qty": 1,
        "dish": "Pan-Roasted Halibut",
        "alterations": [],
        "flagged": [],
    }
    assert order.draft_wire()["type"] == "order.draft"
    assert orders.dispatch("add_item", {"table": 2, "seat": 2, "dish": "soup"})[1] is order


def test_unknown_dish_returns_error_with_closest_names(orders: OrderBook) -> None:
    result, _ = orders.dispatch("add_item", {"table": "T1", "seat": 1, "dish": "tomato sup"})
    assert "not on the menu" in result["error"]
    assert "Roasted Tomato Soup" in result["didYouMean"]


def test_disallowed_alteration_is_flagged_never_applied(orders: OrderBook) -> None:
    result, order = orders.dispatch(
        "add_item",
        {
            "table": "T1",
            "seat": 1,
            "dish": "ribeye",
            "alterations": ["medium rare", "extra cheese"],
        },
    )
    assert result["line"]["alterations"] == ["medium rare"]
    assert result["flagged"] == ["extra cheese"] and "NOT applied" in result["warning"]
    result, _ = orders.dispatch(
        "modify_item", {"table": "T1", "seat": 1, "dish": "steak", "change": "no salt"}
    )
    assert result["applied"] == [] and result["flagged"] == ["no salt"]
    assert order is not None and order.lines[0].flagged == ["extra cheese", "no salt"]


def test_allergy_pins_and_reports_conflicts(orders: OrderBook) -> None:
    orders.dispatch("add_item", {"table": "T3", "seat": 2, "dish": "scallops"})
    result, order = orders.dispatch(
        "set_allergy", {"table": "T3", "seat": 2, "allergen": "Shellfish"}
    )
    assert result["allergyConflicts"] == ["Scallop Crudo contains shellfish"]
    assert order is not None
    assert order.draft_wire()["allergies"] == [{"allergen": "SHELLFISH", "seats": [2]}]
    orders.dispatch("remove_item", {"table": "T3", "seat": 2, "dish": "scallops"})
    assert order.allergies == {2: ["shellfish"]}


def test_bad_arguments_never_raise(orders: OrderBook) -> None:
    assert "error" in orders.dispatch("add_item", "nope")[0]
    assert "error" in orders.dispatch("add_item", {"table": "T1", "seat": 0, "dish": "soup"})[0]
    assert "error" in orders.dispatch("add_item", {"table": "T1", "seat": 1})[0]
    assert "error" in orders.dispatch("add_item", {"table": "T99", "seat": 1, "dish": "soup"})[0]
    assert "error" in orders.dispatch("nuke", {})[0]
    assert (
        "error"
        in orders.dispatch(
            "modify_item", {"table": "T1", "seat": 1, "dish": "soup", "change": "x"}
        )[0]
    )


def test_confirm_and_cancel_only_propose_until_the_tap(orders: OrderBook) -> None:
    _, order = orders.dispatch("add_item", {"table": "T4", "seat": 1, "dish": "duck"})
    assert order is not None
    result, _ = orders.dispatch("confirm_order", {"table": "T4"})
    assert result["status"] == "needs_confirmation" and result["action"] == "confirm"
    assert order.status == "draft" and order.proposal == "confirm"
    assert result["readback"] == "Send T4: 1x Duck Breast?"

    result, _ = orders.dispatch("cancel_order", {"table": "T4", "items": ["duck"]})
    assert result["items"] == ["Duck Breast"] and order.status == "draft"

    assert orders.fire(order.id).status == "fired"
    with pytest.raises(ToolError):
        orders.cancel(order.id)
    assert orders.open_draft("T4") is None


def test_confirm_empty_order_is_an_error(orders: OrderBook) -> None:
    result, _ = orders.dispatch("confirm_order", {"table": "T1"})
    assert "empty" in result["error"]
