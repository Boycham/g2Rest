import pytest

from answers import NOT_IN_MENU, answer, clean_summary, names_food
from order import Menu, OrderBook


@pytest.fixture(scope="module")
def menu() -> Menu:
    return Menu.load()


def said(*words: str):
    heard = set(" ".join(words).lower().split())
    return lambda phrase: all(w in heard or w.rstrip("s") in heard for w in phrase.lower().split())


def ask(menu, **raw):
    return answer(menu, raw, said(raw.get("q", ""), raw.get("allergen", "")))


def test_allergen_answers_come_from_the_menu(menu):
    assert ask(menu, q="risotto have nuts?", kind="allergen", dish="risotto", allergen="nuts") == {
        "q": "risotto have nuts?", "a": "no tree nuts listed for risotto", "answered": True,
    }  # fmt: skip
    a = ask(menu, q="halibut dairy?", kind="allergen", dish="halibut", allergen="dairy")
    assert a["a"] == "yes, halibut has dairy"


def test_the_agents_answer_to_a_food_question_is_never_used(menu):
    a = ask(menu, q="soup has gluten?", kind="allergen", dish="soup", allergen="gluten",
            reply="no, it's gluten free")  # fmt: skip
    assert a["a"] == "yes, soup has gluten"


def test_what_the_menu_cant_answer_is_a_question_mark(menu):
    for raw in (
        {"q": "risotto vegetarian?", "kind": "dietary", "dish": "risotto"},
        {"q": "gluten-free bread?", "kind": "dietary", "dish": "bread", "allergen": "gluten"},
        {"q": "is the duck spicy?", "kind": "prep", "dish": "duck", "reply": "not at all"},
        {"q": "what's in the crudo?", "kind": "ingredients", "dish": "crudo"},
        {"q": "any peanuts?", "kind": "allergen", "allergen": "peanuts"},
    ):
        a = answer(menu, raw, said(raw["q"], raw.get("allergen", "")))
        assert (a["a"], a["answered"]) == (NOT_IN_MENU, False), raw


def test_an_allergen_nobody_said_is_not_answered(menu):
    a = answer(menu, {"q": "risotto ok for me?", "kind": "allergen", "dish": "risotto",
                      "allergen": "gluten"}, said("is the risotto ok for me"))  # fmt: skip
    assert a["answered"] is False


def test_alterations_are_checked_against_the_dish(menu):
    a = ask(menu, q="halibut without butter?", kind="alteration", dish="halibut",
            change="without butter")  # fmt: skip
    assert a["a"] == "yes, no butter is fine"
    a = ask(menu, q="torte without nuts?", kind="alteration", dish="torte", change="no nuts")
    assert a["a"].startswith("has tree nuts; menu allows: no whipped cream, no hazel")
    a = ask(menu, q="salmon without nuts?", kind="alteration", dish="salmon", change="no nuts")
    assert a["a"] == "salmon lists no tree nuts"
    a = ask(menu, q="duck without skin?", kind="alteration", dish="duck", change="no skin")
    assert a == {"q": "duck without skin?", "a": "not an allowed change on the menu",
                 "answered": False}  # fmt: skip


def test_dish_wide_allergen_question_lists_the_menu(menu):
    a = ask(menu, q="what has sesame?", kind="allergen", allergen="sesame")
    assert a["a"] == "sesame in: pork belly"


def test_a_comment_keeps_its_reply_only_if_it_names_no_food(menu):
    ok = ask(menu, q="we're in a rush", kind="comment", reply="I'll fire mains right away")
    assert ok["a"] == "I'll fire mains right away" and ok["answered"]
    for reply in ("the salmon is quickest", "everything is nut free", "want the risotto?"):
        a = ask(menu, q="we're in a rush", kind="comment", reply=reply)
        assert (a["a"], a["answered"]) == (NOT_IN_MENU, False), reply


def test_names_food(menu):
    assert names_food(menu, "the ribeye is great")
    assert names_food(menu, "it's vegan")
    assert not names_food(menu, "happy anniversary, I'll bring it fast")


def test_summary_drops_guesses_and_questions(menu):
    s = clean_summary(menu, "Anniversary, relaxed. Seat 2 is allergic to nuts. Want the duck?",
                      allergies=set(), dishes={"Wild Mushroom Risotto"})  # fmt: skip
    assert s == "Anniversary, relaxed"
    s = clean_summary(menu, "In a rush. Duck for the birthday girl.", set(), {"Duck Breast"})
    assert s == "In a rush. Duck for the birthday girl"


def test_set_order_with_no_dishes_still_carries_summary_and_answers():
    book = OrderBook(Menu.load())
    book.hear("we're in a rush tonight, is the risotto vegetarian, does it have nuts")
    result, err = book.dispatch("set_order", {
        "summary": "In a rush tonight.",
        "questions": [
            {"guest": 2, "q": "risotto vegetarian?", "kind": "dietary", "dish": "risotto"},
            {"guest": 2, "q": "risotto nuts?", "kind": "allergen", "dish": "risotto",
             "allergen": "nuts"},
            {"q": "we're in a rush", "kind": "comment", "reply": "I'll put it in now"},
            {"q": "", "kind": "other"},
        ],
    })  # fmt: skip
    assert not err and not book.tables[0].seats
    t = book.tables[0]
    assert t.summary == "In a rush tonight"
    assert [(a.get("seat"), a["a"]) for a in t.answers] == [
        (1, NOT_IN_MENU), (1, "no tree nuts listed for risotto"), (None, "I'll put it in now"),
    ]  # fmt: skip
    assert result["dropped_questions"] == ["question without text"]
