import pytest

from order import Menu, OrderBook, ToolError


@pytest.fixture
def book() -> OrderBook:
    return OrderBook(Menu.load())


def call(book: OrderBook, tool: str, **params):
    return book.dispatch(tool, params)


def test_menu_has_required_dishes():
    menu = Menu.load()
    assert len(menu.dishes) >= 8  # data/menu.json: the voice spike's 8 dishes plus the backend's
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
    assert book.snapshot() == {"12": {"status": "draft", "seats": {}, "pending_proposals": []}}


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


def test_remove_absent_item_is_an_error(book):
    call(book, "add_item", table=12, seat=2, dish="salmon", qty=1)
    result, err = call(book, "remove_item", table=12, seat=2, dish="soup")
    assert err and "seat 2 has no Roasted Tomato Soup" in result["error"]
    assert "Cedar Plank Salmon" in result["error"]
    assert book.tables[12].proposals == []
    assert [i.dish for i in book.tables[12].seats[2].items] == ["Cedar Plank Salmon"]


def test_remove_on_empty_seat_is_an_error(book):
    result, err = call(book, "remove_item", table=12, seat=4, dish="salmon")
    assert err and "nothing removed" in result["error"]


def test_remove_only_proposes_until_accepted(book):
    call(book, "add_item", table=12, seat=2, dish="soup", qty=1)
    result, err = call(book, "remove_item", table=12, seat=2, dish="tomato soup")
    assert not err and result["status"] == "needs_confirmation"
    assert result["dish"] == "Roasted Tomato Soup"
    assert len(book.tables[12].seats[2].items) == 1
    applied = book.accept(result["id"])
    assert applied["status"] == "applied"
    assert book.tables[12].seats[2].items == []
    assert book.tables[12].proposals == []


def test_noisy_removal_rejected_keeps_dish(book):
    # "no suit for seat two": the agent picks the salmon, which is on the seat.
    call(book, "add_item", table=12, seat=2, dish="salmon", qty=1)
    result, err = call(book, "remove_item", table=12, seat=2, dish="salmon")
    assert not err and result["status"] == "needs_confirmation"
    assert book.reject(result["id"])["status"] == "rejected"
    assert [i.dish for i in book.tables[12].seats[2].items] == ["Cedar Plank Salmon"]
    assert book.tables[12].proposals == []


def test_repeated_proposal_is_not_duplicated(book):
    call(book, "add_item", table=12, seat=2, dish="salmon", qty=1)
    a, _ = call(book, "remove_item", table=12, seat=2, dish="salmon")
    b, _ = call(book, "remove_item", table=12, seat=2, dish="salmon")
    assert a["id"] == b["id"] and len(book.tables[12].proposals) == 1


def test_unknown_proposal_raises_tool_error(book):
    with pytest.raises(ToolError):
        book.accept("p99")
    with pytest.raises(ToolError):
        book.reject("p99")


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
    assert book.tables[12].status == "draft"
    assert [p["action"] for p in book.tables[12].proposals] == ["cancel", "fire"]
    assert book.tables[12].proposals[0]["items"] == ["course:dessert"]


def test_accepting_course_cancel_removes_only_that_course(book):
    call(book, "add_item", table=12, seat=1, dish="halibut", qty=1)
    call(book, "add_item", table=12, seat=1, dish="torte", qty=1)
    result, _ = call(book, "cancel_order", table=12, items=["desserts"])
    book.accept(result["id"])
    assert [i.dish for i in book.tables[12].seats[1].items] == ["Pan-Roasted Halibut"]


def test_cancel_dish_not_on_order_is_an_error(book):
    call(book, "add_item", table=12, seat=1, dish="halibut", qty=1)
    result, err = call(book, "cancel_order", table=12, items=["salmon"])
    assert err and "nothing to cancel" in result["error"]


def test_whole_order_cancel_needs_accept_then_locks_table(book):
    call(book, "add_item", table=12, seat=1, dish="halibut", qty=1)
    call(book, "set_allergy", table=12, seat=1, allergen="fish")
    result, _ = call(book, "cancel_order", table=12)
    assert result["items"] == ["whole order"] and book.tables[12].status == "draft"
    book.accept(result["id"])
    assert book.tables[12].status == "cancelled"
    assert book.tables[12].seats[1].allergies == ["fish"]
    _, err = call(book, "add_item", table=12, seat=1, dish="salmon", qty=1)
    assert err


def test_cancel_course_not_ordered_is_an_error(book):
    call(book, "add_item", table=12, seat=1, dish="halibut", qty=1)
    result, err = call(book, "cancel_order", table=12, items=["dessert"])
    assert err and "no dessert ordered" in result["error"]
    assert book.tables[12].proposals == []


def test_confirm_needs_dishes(book):
    result, err = call(book, "confirm_order", table=12)
    assert err and "nothing to send" in result["error"]


def test_fire_only_with_nothing_pending(book):
    call(book, "add_item", table=12, seat=1, dish="halibut", qty=1)
    call(book, "add_item", table=12, seat=2, dish="salmon", qty=1)
    removal, _ = call(book, "remove_item", table=12, seat=2, dish="salmon")
    with pytest.raises(ToolError):
        book.fire(12)
    fire, _ = call(book, "confirm_order", table=12)
    with pytest.raises(ToolError):
        book.accept(fire["id"])
    book.reject(removal["id"])
    assert book.accept(fire["id"])["status"] == "applied"
    assert book.tables[12].status == "sent"
    _, err = call(book, "remove_item", table=12, seat=1, dish="halibut")
    assert err


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


# ---- set_order: the whole order from one clip ----


def clip_order(**extra):
    return {
        "items": [
            {"guest": 1, "dish": "halibut", "alterations": ["no butter"]},
            {"guest": 2, "dish": "Cedar Plank Salmon", "alterations": ["no dill", "extra cheese"]},
        ],
        "allergies": [{"guest": 2, "allergen": "Shellfish"}],
        "unclear": [{"guest": 3, "text": "'the fish': halibut or salmon"}],
        "notes": ["anniversary"],
        **extra,
    }


def seats(book, t=0):
    return {n: [(i.dish, i.alterations, i.flagged_alterations) for i in s.items]
            for n, s in book.tables[t].seats.items()}  # fmt: skip


def test_set_order_numbers_seats_in_order_of_ordering_and_stays_tableless(book):
    result, err = book.dispatch("set_order", clip_order())
    assert not err and result["table"] is None and "table_unknown" in result
    assert seats(book) == {
        1: [("Pan-Roasted Halibut", ["no butter"], [])],
        2: [("Cedar Plank Salmon", ["no dill"], ["extra cheese"])],
    }
    assert book.tables[0].seats[2].allergies == ["shellfish"]
    assert book.tables[0].uncertain == ["? s3 'the fish': halibut or salmon"]
    assert book.tables[0].notes == ["anniversary"]
    assert result["flagged_not_applied"] == ["s2 Cedar Plank Salmon: extra cheese"]


def test_spoken_seat_wins_and_auto_seats_skip_it(book):
    book.dispatch(
        "set_order",
        {"items": [{"guest": 1, "dish": "soup"}, {"guest": 2, "seat": 1, "dish": "duck"}]},
    )
    assert seats(book) == {2: [("Roasted Tomato Soup", [], [])], 1: [("Duck Breast", [], [])]}


def test_question_lines_are_dropped_in_code(book):
    result, _ = book.dispatch(
        "set_order",
        {"unclear": [{"text": "Which fish did seat 3 want?"}, {"text": "could you confirm"}]},
    )
    assert book.tables[0].uncertain == []
    assert len(result["rejected_unclear"]) == 2


def test_unknown_dish_becomes_a_code_written_unclear_line(book):
    book.dispatch("set_order", {"items": [{"guest": 1, "dish": "branzino"}]})
    line = book.tables[0].uncertain[0]
    assert line.startswith("? s1 'branzino' not on menu:") and "?" not in line[1:]


def test_spoken_table_binds_a_tableless_draft_and_fire_needs_it(book):
    book.dispatch("set_order", clip_order())
    with pytest.raises(ToolError, match="TABLE"):
        book.fire(book.draft_table)
    book.dispatch("set_order", clip_order(table=2))
    assert book.current_table == 2 and 0 not in book.tables
    assert seats(book, 2)[1] == [("Pan-Roasted Halibut", ["no butter"], [])]


def test_order_task_table_is_not_overridden_by_a_spoken_one(book):
    book.bind_table(3, "task")
    result, _ = book.dispatch("set_order", clip_order(table=5))
    assert book.current_table == 3 and "kept table 3" in result["table_notice"]


def test_a_later_clip_can_only_propose_removals(book):
    book.bind_table(3, "task")
    book.dispatch("set_order", clip_order())
    later = clip_order()
    later["items"] = later["items"][1:] + [{"guest": 1, "dish": "risotto"}]
    result, _ = book.dispatch("set_order", later)
    assert result["pending_removals"] == ["s1 Pan-Roasted Halibut"]
    assert [i.dish for i in book.tables[3].seats[1].items] == [
        "Pan-Roasted Halibut",
        "Wild Mushroom Risotto",
    ]
    book.accept(book.tables[3].proposals[0]["id"])
    assert [i.dish for i in book.tables[3].seats[1].items] == ["Wild Mushroom Risotto"]
    assert book.tables[3].seats[2].allergies == ["shellfish"]  # never dropped


def test_set_order_bad_shapes_are_errors_not_crashes(book):
    for params in ({"items": "halibut"}, {"items": [{"guest": "x", "dish": "soup"}]}):
        result, err = book.dispatch("set_order", params)
        assert err and "error" in result


def test_a_guessed_dish_for_an_unclear_guest_is_held_not_applied(book):
    order = clip_order()
    order["items"] = order["items"] + [{"guest": 3, "dish": "nicoise"}]
    result, _ = book.dispatch("set_order", order)
    assert 3 not in book.tables[0].seats or not book.tables[0].seats[3].items
    assert result["held_unclear"] == ["s3 nicoise"]
    assert book.tables[0].uncertain == ["? s3 'the fish': halibut or salmon"]


def test_unclear_guest_keeps_a_clearly_different_second_dish(book):
    order = {
        "items": [{"guest": 1, "dish": "soup"}, {"guest": 1, "dish": "halibut"}],
        "unclear": [{"guest": 1, "text": "'the fish': halibut or salmon"}],
    }
    book.dispatch("set_order", order)
    assert [i.dish for i in book.tables[0].seats[1].items] == ["Roasted Tomato Soup"]


def test_set_order_keeps_only_what_was_said_in_the_clip(book):
    book.hear("I'll have the halibut, no butter. Burrata to share. Shellfish allergy here.")
    result, _ = book.dispatch(
        "set_order",
        {
            "items": [
                {"guest": 1, "dish": "halibut", "alterations": ["no butter", "no capers"]},
                {"guest": 1, "dish": "burrata", "alterations": ["no pesto", "extra tomato"]},
                {"guest": 2, "dish": "nicoise"},
            ],
            "allergies": [{"guest": 1, "allergen": "shellfish"}, {"guest": 2, "allergen": "egg"}],
        },
    )
    seat1 = book.tables[0].seats[1]
    assert [(i.dish, i.alterations) for i in seat1.items] == [
        ("Pan-Roasted Halibut", ["no butter"]),
        ("Burrata", []),
    ]
    assert seat1.allergies == ["shellfish"] and 2 not in book.tables[0].seats
    assert "s2 Nicoise Salad" in result["not_in_clip"] and "allergy egg" in result["not_in_clip"]
