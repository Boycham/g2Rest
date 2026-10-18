"""Clip summary and answers to the table's questions, checked against data/menu.json.

The agent only classifies what a guest asked (kind, dish, allergen, change); code writes
every answer that is about the food from the menu. Anything the menu can't answer becomes a
`?` line ("not in menu data"); nothing is guessed. Only a plain comment ("we're in a rush")
keeps the agent's suggested reply, and only if that reply makes no claim about a dish or an
allergen. Display only: none of this is ever sent to the kitchen.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from order import Dish, Menu, ToolError, _norm, _words, is_question

MAX_ANSWERS = 4
MAX_SUMMARY_CHARS = 120
MAX_Q_CHARS = 40
MAX_A_CHARS = 60
NOT_IN_MENU = "not in menu data"
KINDS = ("allergen", "alteration", "dietary", "ingredients", "prep", "comment", "other")

# What guests say -> the menu's allergen words. "nuts" means tree nuts on this menu (it lists
# no peanuts); "peanut" is its own word, so a peanut question is never answered as tree nuts.
ALLERGEN_WORDS: dict[str, str] = {
    "nut": "tree nuts", "nuts": "tree nuts", "tree nut": "tree nuts", "tree nuts": "tree nuts",
    "dairy": "dairy", "milk": "dairy", "lactose": "dairy", "cheese": "dairy", "butter": "dairy",
    "cream": "dairy", "gluten": "gluten", "wheat": "gluten", "fish": "fish",
    "shellfish": "shellfish", "seafood": "shellfish", "egg": "egg", "eggs": "egg",
    "soy": "soy", "sesame": "sesame", "citrus": "citrus",
}  # fmt: skip
# Dietary words the menu answers through its allergen list: "<x>-free" means "no <allergen>".
FREE_OF = {"gluten": "gluten", "dairy": "dairy", "nut": "tree nuts", "lactose": "dairy",
           "egg": "egg", "soy": "soy", "sesame": "sesame"}  # fmt: skip
# Words that make a claim about food the menu has no data for; never trusted from the agent.
FOOD_CLAIMS = frozenset({
    "vegetarian", "vegan", "pescatarian", "halal", "kosher", "keto", "organic", "spicy",
    "allergen", "allergens", "allergy", "allergic", "peanut", "peanuts", "free", "contains",
    "ingredient", "ingredients", "meat", "stock", "broth", "pork", "chicken", "beef", "raw",
})  # fmt: skip


def _allergen_terms(text: str) -> list[str]:
    """Menu allergens named in `text` ("nut-free" -> tree nuts), in order, no repeats."""
    words = _words(text)
    out: list[str] = []
    for i, w in enumerate(words):
        two = f"{w} {words[i + 1]}" if i + 1 < len(words) else ""
        hit = ALLERGEN_WORDS.get(two) or ALLERGEN_WORDS.get(w)
        if hit and hit not in out:
            out.append(hit)
    return out


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split()).strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def names_food(menu: Menu, text: str) -> bool:
    """True if `text` names a menu dish, an allergen or a food claim word."""
    words = set(_words(text))
    if words & FOOD_CLAIMS or _allergen_terms(text):
        return True
    keys = [k for d in menu.dishes.values() for k in (d.name, *d.aliases)]
    return any(set(_words(k)) <= words for k in keys)


def clean_summary(menu: Menu, text: str, allergies: set[str], dishes: set[str]) -> str:
    """1-2 short sentences about the table. A sentence that names an allergen not on this
    order or a dish nobody ordered is dropped (that would be a guess); so is a question."""
    kept = []
    for raw in text.replace("?", "?.").replace("!", ".").split("."):
        s = raw.strip()
        if not s or s.endswith("?") or is_question(s):
            continue
        if any(a not in allergies for a in _allergen_terms(s)):
            continue
        named = {
            d.name for d in menu.dishes.values() if any(set(_words(k)) <= set(_words(s))
                                                       for k in (d.name, *d.aliases))
        }  # fmt: skip
        if named - dishes:
            continue
        kept.append(s)
    return _clip(". ".join(kept[:2]), MAX_SUMMARY_CHARS)


def _label(dish: Dish) -> str:
    return dish.aliases[0] if dish.aliases else dish.name.lower()


def _allergen_answer(dish: Dish, allergen: str) -> tuple[str, bool]:
    if allergen in dish.allergens:
        return f"yes, {_label(dish)} has {allergen}", True
    return f"no {allergen} listed for {_label(dish)}", True


def _change_answer(dish: Dish, change: str) -> tuple[str, bool]:
    words = set(_words(change))
    for alt in dish.allowed_alterations:
        if set(_words(alt)) - {"no"} <= words:
            return f"yes, {alt} is fine", True
    terms = _allergen_terms(change)
    if terms and words & {"no", "without", "free"}:
        has = [t for t in terms if t in dish.allergens]
        if not has:
            return f"{_label(dish)} lists no {terms[0]}", True
        alts = ", ".join(dish.allowed_alterations) or "none"
        return f"has {has[0]}; menu allows: {alts}", True
    return "not an allowed change on the menu", False


def answer(menu: Menu, raw: dict[str, Any], was_said: Callable[[str], bool]) -> dict[str, Any]:
    """One guest question -> {q, a, answered}. Raises ToolError for an entry to drop."""
    q = str(raw.get("q") or raw.get("question") or "").strip()
    if not q:
        raise ToolError("question without text")
    kind = _norm(str(raw.get("kind") or "other"))
    kind = kind if kind in KINDS else "other"
    dish_name = str(raw.get("dish") or "").strip()
    dish: Dish | None = None
    if dish_name:
        try:
            dish = menu.resolve(dish_name)
        except ToolError:
            return {"q": _clip(q, MAX_Q_CHARS), "a": NOT_IN_MENU, "answered": False}
    said_terms = [t for t in _allergen_terms(f"{raw.get('allergen') or ''} {q}") if was_said(t)
                  or any(was_said(w) for w, a in ALLERGEN_WORDS.items() if a == t)]  # fmt: skip
    a, ok = NOT_IN_MENU, False
    if kind == "comment":
        reply = " ".join(str(raw.get("reply") or "").split())
        if reply and not is_question(reply) and not names_food(menu, reply) and not dish:
            a, ok = reply, True
    elif kind == "alteration" and dish:
        change = str(raw.get("change") or q)
        a, ok = _change_answer(dish, change)
    elif kind in ("allergen", "dietary") and said_terms:
        allergen = said_terms[0]
        if dish:
            a, ok = _allergen_answer(dish, allergen)
        else:
            having = [_label(d) for d in menu.dishes.values() if allergen in d.allergens]
            a, ok = (f"{allergen} in: {', '.join(having)}" if having else
                     f"no {allergen} listed on the menu"), True  # fmt: skip
    return {"q": _clip(q, MAX_Q_CHARS), "a": _clip(a, MAX_A_CHARS), "answered": ok}


def answer_all(
    menu: Menu,
    entries: list[dict[str, Any]],
    seat_of: Callable[[dict[str, Any]], int | None],
    was_said: Callable[[str], bool],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Every question the clip raised -> wire answers (seat?, q, a, answered), plus why any
    entry was dropped (for the tool result)."""
    out: list[dict[str, Any]] = []
    dropped: list[str] = []
    for raw in entries:
        try:
            ans = answer(menu, raw, was_said)
        except ToolError as e:
            dropped.append(str(e))
            continue
        seat = seat_of(raw)
        out.append({**({"seat": seat} if seat else {}), **ans})
    return out[:MAX_ANSWERS], dropped
