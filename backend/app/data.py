"""Loads and validates data/menu.json and data/floor.json (schemas in CONTRACT.md §7)."""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path

COURSES = ("appetizer", "main", "dessert")
TEMPERATURES = ("hot", "warm", "room", "cold")
TABLE_STATUSES = ("empty", "seated", "ordered", "waiting", "eating", "check")


class DataError(ValueError):
    """A data file doesn't match the schema."""


def norm(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").split())


@dataclass(frozen=True)
class Dish:
    name: str
    aliases: tuple[str, ...]
    course: str
    temperature: str
    allergens: tuple[str, ...]
    allowed_alterations: tuple[str, ...]

    @property
    def short(self) -> str:
        """What the floor calls it: "halibut" for Pan-Roasted Halibut."""
        return self.aliases[0] if self.aliases else self.name.lower()


class Menu:
    def __init__(self, restaurant: str, dishes: list[Dish]) -> None:
        self.restaurant = restaurant
        self.dishes: dict[str, Dish] = {}
        self._lookup: dict[str, Dish] = {}
        for dish in dishes:
            if dish.name in self.dishes:
                raise DataError(f"duplicate dish name {dish.name!r}")
            self.dishes[dish.name] = dish
            for key in (dish.name, *dish.aliases):
                self._lookup[norm(key)] = dish

    @classmethod
    def from_dict(cls, raw: dict) -> Menu:
        if not isinstance(raw.get("dishes"), list) or not raw["dishes"]:
            raise DataError("menu needs a non-empty 'dishes' list")
        dishes = []
        for d in raw["dishes"]:
            if d.get("course") not in COURSES:
                raise DataError(f"{d.get('name')}: course must be one of {COURSES}")
            if d.get("temperature") not in TEMPERATURES:
                raise DataError(f"{d.get('name')}: temperature must be one of {TEMPERATURES}")
            dishes.append(
                Dish(
                    name=str(d["name"]),
                    aliases=tuple(d.get("aliases", [])),
                    course=d["course"],
                    temperature=d["temperature"],
                    allergens=tuple(a.lower() for a in d.get("allergens", [])),
                    allowed_alterations=tuple(d.get("allowed_alterations", [])),
                )
            )
        return cls(str(raw.get("restaurant", "")), dishes)

    @classmethod
    def load(cls, path: Path) -> Menu:
        return cls.from_dict(json.loads(path.read_text()))

    def find(self, name: str) -> Dish | None:
        key = norm(name).removeprefix("the ")
        return self._lookup.get(key) or self._lookup.get(key.removesuffix("s"))

    def closest(self, name: str, n: int = 3) -> list[str]:
        key = norm(name)
        scored: dict[str, float] = {}
        for alias, dish in self._lookup.items():
            score = difflib.SequenceMatcher(None, key, alias).ratio()
            if any(w in alias.split() for w in key.split()):
                score += 0.3
            scored[dish.name] = max(scored.get(dish.name, 0.0), score)
        return sorted(scored, key=lambda k: -scored[k])[:n]

    def to_dict(self) -> dict:
        return {
            "restaurant": self.restaurant,
            "dishes": [
                {
                    "name": d.name,
                    "aliases": list(d.aliases),
                    "course": d.course,
                    "temperature": d.temperature,
                    "allergens": list(d.allergens),
                    "allowed_alterations": list(d.allowed_alterations),
                }
                for d in self.dishes.values()
            ],
        }


@dataclass(frozen=True)
class FloorTable:
    id: str
    section: str
    seats: int
    x: float
    y: float


@dataclass(frozen=True)
class Staff:
    id: str
    name: str
    sections: tuple[str, ...]


class Floor:
    def __init__(
        self,
        restaurant: str,
        tables: list[FloorTable],
        servers: list[Staff],
        manager: Staff,
        sections: dict[str, str],
    ) -> None:
        self.restaurant = restaurant
        self.tables = {t.id: t for t in tables}
        self.servers = {s.id: s for s in servers}
        self.manager = manager
        self.sections = sections  # section id -> default server id
        for t in tables:
            if t.section not in sections:
                raise DataError(f"table {t.id} is in unknown section {t.section!r}")
        for sec, server in sections.items():
            if server not in self.servers:
                raise DataError(f"section {sec} names unknown server {server!r}")

    @classmethod
    def from_dict(cls, raw: dict) -> Floor:
        try:
            tables = [
                FloorTable(t["id"], t["section"], int(t["seats"]), float(t["x"]), float(t["y"]))
                for t in raw["tables"]
            ]
            servers = [Staff(s["id"], s["name"], tuple(s["sections"])) for s in raw["servers"]]
            manager = Staff(raw["manager"]["id"], raw["manager"]["name"], ())
            sections = {s["id"]: s["server"] for s in raw["sections"]}
        except (KeyError, TypeError, ValueError) as e:
            raise DataError(f"floor.json: {e!r}") from e
        return cls(str(raw.get("restaurant", "")), tables, servers, manager, sections)

    @classmethod
    def load(cls, path: Path) -> Floor:
        return cls.from_dict(json.loads(path.read_text()))

    def table(self, table_id: str) -> FloorTable:
        try:
            return self.tables[table_id]
        except KeyError:
            raise DataError(f"unknown table {table_id!r}") from None

    def servers_for_section(self, section: str) -> list[str]:
        """The section's default server first, then anyone else who covers it."""
        first = self.sections[section]
        rest = [s.id for s in self.servers.values() if section in s.sections and s.id != first]
        return [first, *rest]

    def escalation_chain(self, table_id: str) -> list[str]:
        """Who a task for this table goes to, in order: section servers, other servers, manager."""
        section = self.table(table_id).section
        chain = self.servers_for_section(section)
        chain += [s for s in self.servers if s not in chain]
        return [*chain, self.manager.id]

    def to_dict(self) -> dict:
        return {
            "restaurant": self.restaurant,
            "sections": [{"id": k, "server": v} for k, v in self.sections.items()],
            "servers": [
                {"id": s.id, "name": s.name, "sections": list(s.sections)}
                for s in self.servers.values()
            ],
            "manager": {"id": self.manager.id, "name": self.manager.name},
            "tables": [
                {"id": t.id, "section": t.section, "seats": t.seats, "x": t.x, "y": t.y}
                for t in self.tables.values()
            ],
        }
