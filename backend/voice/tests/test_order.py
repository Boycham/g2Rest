import pytest

from order import Menu, OrderBook


@pytest.fixture
def book() -> OrderBook:
    return OrderBook(Menu.load())


def call(book: OrderBook, tool: str, **params):
    return book.dispatch(tool, params)


def test_menu_has_required_dishes():
    menu = Menu.load()
    assert len(menu.dishes) == 8
    courses = {d.course for d in menu.dishes.values()}
    assert courses == {"appetizer", "main", "dessert"}
    for word in ("halibut", "salmon", "soup", "torte"):
        assert menu.resolve(word)


def test_alias_and_case_resolve_to_menu_name(book):
    result, err = call(book, "add_item", table=12, seat=1, dish="the Halibut", qty=1)
    assert not err
    assert result["added"] == "Pan-Roasted Halibut"


def test_unknown_dish_is_error_with_suggestions(book):
    result, err = call(book, "add_item", table=12, seat=1, dish="halibutt", qty=1)
    assert err
    assert "not on the menu" in result["error"]
    assert "Pan-Roasted Halibut" in result["error"]
    assert book.snapshot() == {"12": {"seats": {}, "pending_proposals": []}}


def test_allowed_alteration_applied(book):
    result, err = call(
        book, "add_item", table=12, seat=1, dish="halibut", qty=1, alterations=["No Butter"]
    )
    assert not err
    item = book.tables[12].seats[1].items[0]
    assert item.alterations == ["no butter"]
    assert item.flagged_alterations == []
    assert "warning" not in result


def test_disallowed_alteration_flagged_not_applied(book):
    result, err = call(
        book,
        "add_item",
        table=12,
        seat=2,
        dish="salmon",
        qty=1,
        alterations=["no dill", "extra truffle"],
    )
    assert not err
    item = book.tables[12].seats[2].items[0]
    assert item.alterations == ["no dill"]
    assert item.flagged_alterations == ["extra truffle"]
    assert result["flagged_alterations"] == ["extra truffle"]


def test_modify_item_guards_alteration(book):
    call(book, "add_item", table=12, seat=1, dish="halibut", qty=1)
    _, err = call(book, "modify_item", table=12, seat=1, dish="halibut", change="no butter")
    assert not err
    result, err = call(book, "modify_item", table=12, seat=1, dish="halibut", change="add bacon")
    assert not err and result["flagged_alterations"] == ["add bacon"]
    item = book.tables[12].seats[1].items[0]
    assert item.alterations == ["no butter"]
    assert item.flagged_alterations == ["add bacon"]


def test_modify_missing_item_is_error(book):
    result, err = call(book, "modify_item", table=12, seat=1, dish="salmon", change="no dill")
    assert err and "add it first" in result["error"]


def test_remove_absent_item_is_not_an_error(book):
    result, err = call(book, "remove_item", table=12, seat=2, dish="soup")
    assert not err and result["status"] == "not_found"


def test_remove_item(book):
    call(book, "add_item", table=12, seat=2, dish="soup", qty=1)
    result, err = call(book, "remove_item", table=12, seat=2, dish="tomato soup")
    assert not err and result["removed"] == "Roasted Tomato Soup"
    assert book.tables[12].seats[2].items == []


def test_allergy_pinned_and_conflict_reported(book):
    call(book, "set_allergy", table=12, seat=3, allergen="Shellfish")
    result, err = call(book, "add_item", table=12, seat=3, dish="scallop crudo", qty=1)
    assert not err
    assert result["allergy_conflicts"] == ["Scallop Crudo contains shellfish"]
    call(book, "remove_item", table=12, seat=3, dish="scallop crudo")
    assert book.tables[12].seats[3].allergies == ["shellfish"]


def test_confirm_and_cancel_only_propose(book):
    call(book, "add_item", table=12, seat=1, dish="torte", qty=1)
    result, err = call(book, "cancel_order", table=12, items=["dessert"])
    assert not err and result["status"] == "needs_confirmation"
    result, err = call(book, "confirm_order", table=12)
    assert not err and result["status"] == "needs_confirmation"
    assert len(book.tables[12].seats[1].items) == 1
    assert [p["action"] for p in book.tables[12].proposals] == ["cancel", "fire"]
    assert book.tables[12].proposals[0]["items"] == ["course:dessert"]


@pytest.mark.parametrize(
    "tool,params",
    [
        ("add_item", {"table": "twelve", "seat": 1, "dish": "halibut"}),
        ("add_item", {"table": 12, "seat": 0, "dish": "halibut"}),
        ("add_item", {"table": 12, "seat": 1, "dish": "halibut", "qty": 1.5}),
        ("add_item", {"table": 12, "seat": 1, "dish": ""}),
        ("add_item", {"table": 12, "seat": 1, "dish": "halibut", "alterations": [3]}),
        ("set_allergy", {"table": 12, "seat": 1}),
        ("cancel_order", {"table": 12, "items": ["pizza"]}),
        ("fire_order", {"table": 12}),
        ("add_item", ["not", "a", "dict"]),
    ],
)
def test_bad_calls_return_errors_without_raising(book, tool, params):
    result, err = book.dispatch(tool, params)
    assert err and "error" in result


def test_numeric_strings_are_accepted(book):
    result, err = call(book, "add_item", table="12", seat="2", dish="salmon", qty="1")
    assert not err and result["table"] == 12 and result["seat"] == 2


def test_speech_end_offset_finds_last_voiced_frame():
    import array

    from voice_session import FRAME_BYTES, speech_end_offset

    loud = array.array("h", [8000, -8000] * (FRAME_BYTES // 4)).tobytes()
    pcm = bytes(FRAME_BYTES) + loud * 3 + bytes(FRAME_BYTES) * 5
    assert speech_end_offset(pcm) == pytest.approx(0.4)
