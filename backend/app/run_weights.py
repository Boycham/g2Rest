"""Every number the run-priority engine uses, in one place, so the simulator can tune them.

Score of a plate that is up at the pass (`app/runs.py`):

    base  = course[course] * course_weight + temperature[temperature]
    score = base + decay[temperature] * minutes_up   (+ ceiling_bonus once minutes_up > ceiling_min)

`course_weight` keeps course above temperature: with the defaults a cold appetizer (12) still beats
a hot main (11). `ceiling_bonus` is large so any plate past the ceiling is at the top whatever its
course.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RunWeights:
    course: dict[str, float] = field(
        default_factory=lambda: {"appetizer": 3, "main": 2, "dessert": 1}
    )
    temperature: dict[str, float] = field(
        default_factory=lambda: {"hot": 3, "warm": 2, "room": 1, "cold": 0}
    )
    course_weight: float = 4.0
    decay: dict[str, float] = field(
        default_factory=lambda: {"hot": 3, "warm": 2, "room": 1, "cold": 1}
    )
    ceiling_min: float = 5.0
    ceiling_bonus: float = 1000.0
    max_plates_per_runner: int = 3

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RunWeights:
        base = cls()
        return cls(
            course={**base.course, **raw.get("course", {})},
            temperature={**base.temperature, **raw.get("temperature", {})},
            course_weight=float(raw.get("course_weight", base.course_weight)),
            decay={**base.decay, **raw.get("decay", {})},
            ceiling_min=float(raw.get("ceiling_min", base.ceiling_min)),
            ceiling_bonus=float(raw.get("ceiling_bonus", base.ceiling_bonus)),
            max_plates_per_runner=int(raw.get("max_plates_per_runner", base.max_plates_per_runner)),
        )


DEFAULT_WEIGHTS = RunWeights()
