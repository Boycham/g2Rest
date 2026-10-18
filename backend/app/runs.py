"""The pass: plates waiting to be run, and two planners (priority, FIFO) that turn them into runs.

Rules (all in code, all tested in tests/test_runs.py; numbers in app/run_weights.py):

- A plate scores by course above temperature, then rises with its wait at the pass (hot fastest);
  any plate up longer than the ceiling goes to the top.
- A table's course leaves only when all of its plates are up. Until then it is a `Hold` that names
  the plates it waits on.
- A run that carries a hot plate pulls in other all-hot ready courses from the same section, up to
  `max_plates_per_runner` per runner; a course bigger than one runner gets more runners.
- Cold never delays hot: a cold plate joins a hot run only if it is for the same table and already
  up. Cold plates for other tables run on their own.
- FIFO (the baseline) ignores all of that: plates leave in the order they came up, three at a time.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal

from app.data import Floor, Menu
from app.run_weights import DEFAULT_WEIGHTS, RunWeights

PlateStatus = Literal["waiting", "up", "running"]
Planner = Literal["priority", "fifo"]


class PassError(ValueError):
    """Unknown plate, order not fired, or plate already up."""


@dataclass
class Plate:
    id: str  # "<orderId>:<line>"
    order_id: str
    line: int
    table: str
    section: str
    seat: int
    dish: str
    course: str
    temperature: str
    ordered_at: float
    up_at: float | None = None
    run_id: str | None = None

    @property
    def status(self) -> PlateStatus:
        if self.run_id is not None:
            return "running"
        return "up" if self.up_at is not None else "waiting"

    @property
    def hot(self) -> bool:
        return self.temperature == "hot"

    def minutes_up(self, now: float) -> float:
        return 0.0 if self.up_at is None else max(0.0, now - self.up_at) / 60

    def score(self, now: float, w: RunWeights = DEFAULT_WEIGHTS) -> float:
        if self.up_at is None:
            return 0.0
        base = w.course[self.course] * w.course_weight + w.temperature[self.temperature]
        minutes = self.minutes_up(now)
        bonus = w.ceiling_bonus if minutes > w.ceiling_min else 0.0
        return round(base + w.decay[self.temperature] * minutes + bonus, 3)

    def wire(self, now: float, w: RunWeights = DEFAULT_WEIGHTS) -> dict[str, Any]:
        return {
            "plateId": self.id,
            "orderId": self.order_id,
            "line": self.line,
            "table": self.table,
            "seat": self.seat,
            "dish": self.dish,
            "course": self.course,
            "temperature": self.temperature,
            "upSec": int(now - self.up_at) if self.up_at is not None else 0,
            "score": self.score(now, w),
            "status": self.status,
        }


@dataclass
class Course:
    """All the plates of one course for one table that are not yet running."""

    table: str
    course: str
    plates: list[Plate]

    @property
    def ready(self) -> bool:
        return all(p.up_at is not None for p in self.plates)

    @property
    def waiting_on(self) -> list[str]:
        return [p.dish for p in self.plates if p.up_at is None]

    @property
    def all_hot(self) -> bool:
        return all(p.hot for p in self.plates)

    def score(self, now: float, w: RunWeights) -> float:
        return max(p.score(now, w) for p in self.plates)

    @property
    def section(self) -> str:
        return self.plates[0].section


@dataclass
class Hold:
    table: str
    course: str
    waiting_on: list[str]

    def wire(self) -> dict[str, Any]:
        return {"table": self.table, "course": self.course, "waitingOn": list(self.waiting_on)}


@dataclass
class Run:
    id: str
    plates: list[Plate]
    runners: int
    score: float
    reason: str
    assignees: list[str] = field(default_factory=list)

    @property
    def table(self) -> str:
        return self.plates[0].table

    @property
    def tables(self) -> list[str]:
        seen: dict[str, None] = {}
        for p in self.plates:
            seen.setdefault(p.table, None)
        return list(seen)

    @property
    def section(self) -> str:
        return self.plates[0].section

    @property
    def hot(self) -> bool:
        return any(p.hot for p in self.plates)

    def wire(self, now: float, w: RunWeights = DEFAULT_WEIGHTS) -> dict[str, Any]:
        return {
            "runId": self.id,
            "tables": self.tables,
            "section": self.section,
            "runners": self.runners,
            "assignees": list(self.assignees),
            "score": self.score,
            "hot": self.hot,
            "reason": self.reason,
            "plates": [p.wire(now, w) for p in self.plates],
        }


# ---------- grouping ----------


def courses(plates: list[Plate]) -> list[Course]:
    """Every (table, course) with at least one plate not running, in first-ordered order."""
    by_key: dict[tuple[str, str], list[Plate]] = defaultdict(list)
    for p in sorted(plates, key=lambda p: (p.ordered_at, p.line)):
        if p.run_id is None:
            by_key[(p.table, p.course)].append(p)
    return [Course(t, c, ps) for (t, c), ps in by_key.items()]


def holds(plates: list[Plate]) -> list[Hold]:
    """Courses that cannot leave yet and the plates they wait for (the 'holding' plates)."""
    return [Hold(c.table, c.course, c.waiting_on) for c in courses(plates) if not c.ready]


# ---------- planners ----------


def plan_priority(
    plates: list[Plate], now: float, w: RunWeights = DEFAULT_WEIGHTS, run_seq: int = 1
) -> list[Run]:
    """Ready courses by score; hot runs pull in other all-hot ready courses from the section."""
    ready = sorted(
        (c for c in courses(plates) if c.ready),
        key=lambda c: (-c.score(now, w), c.plates[0].up_at or 0.0),
    )
    runs: list[Run] = []
    taken: set[tuple[str, str]] = set()
    for lead in ready:
        key = (lead.table, lead.course)
        if key in taken:
            continue
        taken.add(key)
        chosen = list(lead.plates)
        notes = [f"{lead.table} {lead.course}s x{len(lead.plates)}"]
        if any(p.hot for p in chosen):
            # same table, already up: anything (cold included) may ride along
            for other in ready:
                k = (other.table, other.course)
                if k not in taken and other.table == lead.table:
                    taken.add(k)
                    chosen += other.plates
                    notes.append(f"+ {other.table} {other.course}s x{len(other.plates)}")
            runners = max(1, math.ceil(len(chosen) / w.max_plates_per_runner))
            spare = runners * w.max_plates_per_runner - len(chosen)
            # other tables, same section: only all-hot courses, only into spare hands
            for other in ready:
                k = (other.table, other.course)
                if k in taken or other.section != lead.section or not other.all_hot:
                    continue
                if len(other.plates) > spare:
                    continue
                taken.add(k)
                chosen += other.plates
                spare -= len(other.plates)
                notes.append(f"+ {other.table} hot x{len(other.plates)}")
        else:
            runners = max(1, math.ceil(len(chosen) / w.max_plates_per_runner))
        if runners > 1:
            notes.append(f"{runners} runners")
        runs.append(Run(f"run-{run_seq}", chosen, runners, lead.score(now, w), ", ".join(notes)))
        run_seq += 1
    return runs


def plan_fifo(
    plates: list[Plate], now: float, w: RunWeights = DEFAULT_WEIGHTS, run_seq: int = 1
) -> list[Run]:
    """Baseline: every plate that is up leaves in the order it came up, up to one runner's load."""
    up = sorted(
        (p for p in plates if p.run_id is None and p.up_at is not None),
        key=lambda p: (p.up_at or 0.0, p.ordered_at, p.line),
    )
    runs: list[Run] = []
    n = w.max_plates_per_runner
    for i in range(0, len(up), n):
        chunk = up[i : i + n]
        runs.append(Run(f"run-{run_seq}", chunk, 1, 0.0, "fifo " + ", ".join(p.id for p in chunk)))
        run_seq += 1
    return runs


PLANNERS = {"priority": plan_priority, "fifo": plan_fifo}


# ---------- the pass itself ----------


@dataclass
class Pass:
    menu: Menu
    floor: Floor
    weights: RunWeights = DEFAULT_WEIGHTS
    planner: Planner = "priority"
    plates: dict[str, Plate] = field(default_factory=dict)
    runs: dict[str, Run] = field(default_factory=dict)
    # free servers held for the best run, which needs more hands than are free (server -> run)
    reserved: dict[str, str] = field(default_factory=dict)
    _seq: int = 1

    def add_order(self, order_id: str, table: str, lines: list[Any], now: float) -> list[Plate]:
        """One plate per order line (even when qty > 1), as the kitchen ticket shows it."""
        section = self.floor.table(table).section
        added = []
        for i, ln in enumerate(lines):
            dish = self.menu.find(ln.dish)
            if dish is None:
                raise PassError(f"{order_id} line {i}: {ln.dish!r} is not on the menu")
            plate = Plate(
                id=f"{order_id}:{i}",
                order_id=order_id,
                line=i,
                table=table,
                section=section,
                seat=ln.seat,
                dish=dish.name,
                course=dish.course,
                temperature=dish.temperature,
                ordered_at=now,
            )
            self.plates[plate.id] = plate
            added.append(plate)
        return added

    def mark_up(self, order_id: str, line: int, now: float) -> Plate:
        plate = self.plates.get(f"{order_id}:{line}")
        if plate is None:
            raise PassError(
                f"no plate {order_id}:{line} at the pass (order not fired, or bad line)"
            )
        if plate.up_at is not None:
            raise PassError(f"{plate.id} ({plate.dish}) is already up")
        plate.up_at = now
        return plate

    def dispatch(
        self, now: float, free: dict[str, str] | None = None, extra: dict[str, str] | None = None
    ) -> list[Run]:
        """Plan, then hand runs to free runners in score order; the rest wait at the pass.

        `free` maps a free server to their section. The best run takes the section's free
        servers first, then anyone else free. When it needs more hands than are free, nothing
        below it goes either: the free hands are reserved for it (`reserved`, which also keeps
        new floor tasks off them), so a big course is never starved by a stream of single
        plates. Waiting costs no heat (a busy server could not carry it sooner) and is what
        lets scoring and pairing happen. `free=None` means everyone is free (pure planner tests).

        Past the ceiling a run stops waiting for hands: it leaves with whoever is free, then
        `extra` (the manager, if free), each carrying up to `max_plates_per_runner`. Plates
        nobody can carry yet stay at the pass, on top, for the next free hands.
        """
        runs = PLANNERS[self.planner](list(self.plates.values()), now, self.weights, self._seq)
        pool = dict(free) if free is not None else None
        spare = dict(extra or {})
        self.reserved = {}
        chosen: list[Run] = []
        for run in runs:
            if pool is not None:
                same = [s for s, sec in pool.items() if sec == run.section]
                picks = (same + [s for s in pool if s not in same])[: run.runners]
                if len(picks) < run.runners:
                    if not self.past_ceiling(run, now):
                        self.reserved = dict.fromkeys(picks, run.id)
                        break
                    picks += [s for s in spare if s not in picks][: run.runners - len(picks)]
                    if not picks:
                        break
                    self._shrink(run, len(picks), now)
                for s in picks:
                    pool.pop(s, None)
                    spare.pop(s, None)
                run.assignees = picks
            self.runs[run.id] = run
            for p in run.plates:
                p.run_id = run.id
            self._seq += 1
            chosen.append(run)
        return chosen

    def past_ceiling(self, run: Run, now: float) -> bool:
        return any(p.minutes_up(now) > self.weights.ceiling_min for p in run.plates)

    def _shrink(self, run: Run, runners: int, now: float) -> None:
        """Cut a run down to `runners` pairs of hands: the highest-scoring plates go first."""
        cap = runners * self.weights.max_plates_per_runner
        if cap < len(run.plates):
            ranked = sorted(run.plates, key=lambda p: (-p.score(now, self.weights), p.up_at or 0))
            keep = {p.id for p in ranked[:cap]}
            run.plates = [p for p in run.plates if p.id in keep]
        run.reason += f", past {self.weights.ceiling_min:g} min: {runners} of {run.runners} runners"
        run.runners = runners

    def holds(self) -> list[Hold]:
        return holds(list(self.plates.values()))

    def state(self, now: float) -> dict[str, Any]:
        order = {"up": 0, "waiting": 1, "running": 2}
        plates = sorted(
            self.plates.values(),
            key=lambda p: (order[p.status], -p.score(now, self.weights), p.ordered_at, p.line),
        )
        return {
            "type": "pass.state",
            "planner": self.planner,
            "plates": [p.wire(now, self.weights) for p in plates],
            "holds": [h.wire() for h in self.holds()],
            "runs": [r.wire(now, self.weights) for r in self.runs.values()][-20:],
        }
