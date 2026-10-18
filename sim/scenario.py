"""The fictional service: parties, their dishes and every duration, drawn once from the seed.

Everything random about the guests and the kitchen is drawn here, up front, so the FIFO and the
priority run serve exactly the same parties with the same cook and eating times. Only what the
planner changes (when food reaches the table, and so when the next course and the next party
start) differs between the two runs. Runner reaction and travel times are drawn per server
during the run (`engine.Runner`), from their own seeded streams.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SIM_DIR = Path(__file__).resolve().parent
REPO = SIM_DIR.parent
DEFAULT_SCENARIO = SIM_DIR / "scenario.json"
COURSES = ("appetizer", "main", "dessert")


@dataclass
class Party:
    id: str
    arrive_sec: float
    size: int
    dishes: dict[str, list[tuple[int, str]]]  # course -> [(seat, dish)]
    sec: dict[str, float]  # every duration this party needs, in seconds
    jitter: dict[str, list[float]]  # course -> per-plate offset from the course's target
    table: str | None = None
    order_ids: dict[str, str] = field(default_factory=dict)  # course -> order id
    delivered: set[str] = field(default_factory=set)

    @property
    def plates(self) -> int:
        return sum(len(v) for v in self.dishes.values())


def load(path: Path = DEFAULT_SCENARIO) -> dict[str, Any]:
    return json.loads(path.read_text())


def load_menu() -> dict[str, Any]:
    return json.loads((REPO / "data" / "menu.json").read_text())


def load_floor() -> dict[str, Any]:
    return json.loads((REPO / "data" / "floor.json").read_text())


def dish_table(menu: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {
        d["name"]: {"course": d["course"], "temperature": d["temperature"]} for d in menu["dishes"]
    }


def build(scn: dict[str, Any], menu: dict[str, Any], seed: int | None = None) -> list[Party]:
    rng = random.Random(scn["seed"] if seed is None else seed)
    by_course = {c: [d["name"] for d in menu["dishes"] if d["course"] == c] for c in COURSES}
    sizes = [int(k) for k in scn["party_size_weights"]]
    weights = list(scn["party_size_weights"].values())

    def minutes(key: str) -> float:
        lo, hi = scn["minutes"][key]
        return rng.uniform(lo, hi) * 60

    arrivals = []
    for bucket, count in enumerate(scn["arrivals_per_15min"]):
        arrivals += [rng.uniform(bucket * 900, (bucket + 1) * 900) for _ in range(count)]
    parties = []
    for i, arrive in enumerate(sorted(arrivals)):
        size = rng.choices(sizes, weights)[0]
        dishes: dict[str, list[tuple[int, str]]] = {c: [] for c in COURSES}
        for seat in range(1, size + 1):
            if rng.random() < scn["appetizer_share"]:
                dishes["appetizer"].append((seat, rng.choice(by_course["appetizer"])))
            dishes["main"].append((seat, rng.choice(by_course["main"])))
            if rng.random() < scn["dessert_share"]:
                dishes["dessert"].append((seat, rng.choice(by_course["dessert"])))
        sec = {key: minutes(key) for key in scn["minutes"]}
        jitter = {
            c: [rng.uniform(0, scn["plate_jitter_sec"][c]) for _ in dishes[c]] for c in COURSES
        }
        parties.append(Party(f"P{i + 1:02d}", round(arrive, 1), size, dishes, sec, jitter))
    return parties
