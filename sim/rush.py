"""Dinner-rush simulator: one two-hour service, FIFO vs priority, hot-plate wait side by side.

    cd sim && ../backend/.venv/bin/python rush.py                 # offline, seconds, both planners
    cd sim && ../backend/.venv/bin/python rush.py --live          # drive a running backend

See sim/NOTES.md for the numbers and what they mean.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

SIM_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SIM_DIR.parent / "backend"))

import metrics  # noqa: E402
import scenario  # noqa: E402
from engine import run_offline  # noqa: E402

PLANNERS = ("fifo", "priority")


def offline(scn: dict[str, Any], seed: int, planners: tuple[str, ...]) -> dict[str, Any]:
    menu, floor = scenario.load_menu(), scenario.load_floor()
    dishes = scenario.dish_table(menu)
    servers = [s["id"] for s in floor["servers"]]
    out: dict[str, Any] = {}
    for planner in planners:
        parties = scenario.build(scn, menu, seed)
        res = asyncio.run(run_offline(scn, parties, planner, seed))
        m = metrics.compute(res.events, dishes, servers)
        m["parties"] = len(parties)
        m["served"] = res.world.left
        m["finished"] = res.world.finished
        out[planner] = m
        out.setdefault("_events", {})[planner] = res.events
    return out


ROWS: list[tuple[str, Any]] = [
    ("parties served", lambda m: f"{m['served']}/{m['parties']}"),
    ("service end (min)", lambda m: round(m["serviceEndSec"] / 60, 1)),
    ("plates", lambda m: m["plates"]),
]


def table(results: dict[str, dict[str, Any]], servers: list[str]) -> str:
    names = [p for p in results if not p.startswith("_")]
    rows: list[tuple[str, list[Any]]] = []

    def add(label: str, f: Any) -> None:
        rows.append((label, [f(results[p]) for p in names]))

    for label, f in ROWS:
        add(label, f)
    for temp in metrics.TEMPERATURES:
        add(f"{temp} plates", lambda m, t=temp: m["waitSec"][t]["n"])
        for stat in ("median", "p90", "max"):
            add(f"  {temp} wait {stat} (s)", lambda m, t=temp, s=stat: m["waitSec"][t][s])
    add("hot plate to table median (s)", lambda m: m["toTableSec"]["hot"]["median"])
    add("hot plate to table p90 (s)", lambda m: m["toTableSec"]["hot"]["p90"])
    add("hot plate to table max (s)", lambda m: m["toTableSec"]["hot"]["max"])
    add("hot wait after course up p90 (s)", lambda m: m["hotWaitAfterCourseUpSec"]["p90"])
    add("hot course whole at table median (s)", lambda m: m["hotCourseToTableSec"]["median"])
    add("hot course whole at table p90 (s)", lambda m: m["hotCourseToTableSec"]["p90"])
    add("plates over 5 min ceiling", lambda m: m["ceilingPlates"]["total"])
    add("  of them hot", lambda m: m["ceilingPlates"]["hot"])
    add("plates left at the pass", lambda m: m["stillAtPass"]["total"])
    add("runs", lambda m: m["runs"])
    add("RUN tasks (trips)", lambda m: m["runTasks"])
    staff = sorted({w for p in names for w in results[p]["runTasksDoneBy"]})
    add("runs pairing 2+ tables", lambda m: m["multiTableRuns"])
    add("RUN tasks escalated", lambda m: m["escalatedRunTasks"])
    add("courses left together", lambda m: f"{m['courses']['leftTogether']}/{m['courses']['n']}")
    add("course spread p90 (s)", lambda m: m["courses"]["spreadSec"]["p90"])
    add("idle while reserved (s)", lambda m: m["idleReservedSec"]["total"])
    for s in servers:
        add(f"  {s}", lambda m, s=s: m["idleReservedSec"]["perServer"].get(s, 0))
    add("  of it empty-handed (s)", lambda m: m["idleReservedSec"]["emptyHanded"])
    for who in staff:
        add(f"  RUN trips by {who}", lambda m, w=who: m["runTasksDoneBy"].get(w, 0))
    add("floor tasks escalated", lambda m: m["escalatedFloorTasks"])
    width = max(len(r[0]) for r in rows) + 2
    lines = [f"{'':<{width}}" + "".join(f"{n:>12}" for n in names)]
    for label, vals in rows:
        lines.append(f"{label:<{width}}" + "".join(f"{_fmt(v):>12}" for v in vals))
    return "\n".join(lines)


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.0f}" if abs(v) >= 100 else f"{v:.1f}"
    return str(v)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scenario", type=Path, default=scenario.DEFAULT_SCENARIO)
    ap.add_argument("--seed", type=int, help="override the scenario's seed")
    ap.add_argument("--planners", default=",".join(PLANNERS))
    ap.add_argument("--out", type=Path, default=SIM_DIR / "out")
    ap.add_argument("--live", action="store_true", help="drive a running backend at demo speed")
    ap.add_argument("--url", default="http://localhost:8787")
    ap.add_argument("--token", default="")
    ap.add_argument("--speed", type=float, default=40.0, help="--live: sim seconds per second")
    args = ap.parse_args(argv)

    scn = scenario.load(args.scenario)
    seed = scn["seed"] if args.seed is None else args.seed
    planners = tuple(p.strip() for p in args.planners.split(",") if p.strip())
    servers = [s["id"] for s in scenario.load_floor()["servers"]]
    args.out.mkdir(parents=True, exist_ok=True)
    if args.live:
        from live import run_live

        results = run_live(scn, seed, planners, args.url, args.token, args.speed)
        mode = f"live x{args.speed:g} against {args.url}"
    else:
        results = offline(scn, seed, planners)
        mode = "offline, simulated clock"
    events = results.pop("_events", {})
    stem = f"rush-{'live-' if args.live else ''}{seed}"
    for planner, evs in events.items():
        with (args.out / f"{stem}-{planner}-events.jsonl").open("w") as f:
            for e in evs:
                f.write(json.dumps(e) + "\n")
    report = {"scenario": scn["name"], "seed": seed, "mode": mode, "planners": results}
    (args.out / f"{stem}.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"[fs] {scn['name']}, seed {seed}, {mode}")
    print(table(results, servers))
    print(f"[fs] wrote {args.out / (stem + '.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
