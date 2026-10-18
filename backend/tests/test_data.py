from __future__ import annotations

import pytest

from app.data import COURSES, TEMPERATURES, DataError, Floor, Menu


def test_menu_has_every_course_and_temperature(menu: Menu) -> None:
    assert {d.course for d in menu.dishes.values()} == set(COURSES)
    assert {d.temperature for d in menu.dishes.values()} == set(TEMPERATURES)


def test_menu_resolves_aliases_case_and_plural(menu: Menu) -> None:
    assert menu.find("halibut").name == "Pan-Roasted Halibut"
    assert menu.find("The Scallops").name == "Scallop Crudo"
    assert menu.find("Chocolate Cake").name == "Dark Chocolate Torte"
    assert menu.find("pizza") is None
    assert "Roasted Tomato Soup" in menu.closest("tomato sup")


def test_menu_rejects_bad_course() -> None:
    with pytest.raises(DataError):
        Menu.from_dict({"dishes": [{"name": "x", "course": "snack", "temperature": "hot"}]})


def test_floor_shape(floor: Floor) -> None:
    assert len(floor.tables) == 8
    assert len(floor.sections) == 2
    assert len(floor.servers) == 2
    assert floor.escalation_chain("T1") == ["s1", "s2", "m1"]
    assert floor.escalation_chain("T8") == ["s2", "s1", "m1"]


def test_floor_rejects_unknown_section() -> None:
    raw = {
        "sections": [{"id": "A", "server": "s1"}],
        "servers": [{"id": "s1", "name": "A", "sections": ["A"]}],
        "manager": {"id": "m1", "name": "M"},
        "tables": [{"id": "T1", "section": "Z", "seats": 2, "x": 0, "y": 0}],
    }
    with pytest.raises(DataError):
        Floor.from_dict(raw)
