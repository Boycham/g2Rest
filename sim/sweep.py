"""Seed sweep: FIFO vs priority hot pass wait over many services, plus the course-hold floor.

    cd sim && ../backend/.venv/bin/python sweep.py                  # seeds 1-20, ~35 s
    cd sim && ../backend/.venv/bin/python sweep.py --seeds 1-5 20261018
    cd sim && ../backend/.venv/bin/python sweep.py --what-if no-course-hold

The floor is the wait the "whole course goes out together" rule alone forces on each hot plate
(`metrics.hotCourseHoldSec`); it is the same for every planner. `--what-if no-course-hold` is an
experiment only: it patches the pass in this process so a course may leave plate by plate,
which breaks a build-plan rule, to show how much of the gap the rule explains.
See sim/NOTES.md.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

import rush
import scenario

STATS = ("median", "p90")


def parse_seeds(raw: list[str]) -> list[int]:
    seeds: list[int] = []
    for item in raw:
        lo, _, hi = item.partition("-")
        seeds += list(range(int(lo), int(hi) + 1)) if hi else [int(lo)]
    return seeds


def no_course_hold() -> None:
    from app import runs

    real = runs.courses
    runs.courses = lambda plates: real([p for p in plates if p.up_at is not None])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--seeds", nargs="+", default=["1-20"])
    ap.add_argument("--what-if", choices=["no-course-hold"])
    ap.add_argument("--out", type=Path, default=rush.SIM_DIR / "out")
    args = ap.parse_args(argv)
    if args.what_if == "no-course-hold":
        no_course_hold()
    scn = scenario.load(scenario.DEFAULT_SCENARIO)
    rows: list[dict[str, Any]] = []
    print(
        "[fs] hot pass wait (s), median / p90"
        + (f", what-if {args.what_if}" if args.what_if else "")
    )
    print(f"{'seed':>9} {'fifo':>13} {'priority':>13} {'hold floor':>13}")
    for seed in parse_seeds(args.seeds):
        res = rush.offline(scn, seed, rush.PLANNERS)
        row = {
            "seed": seed,
            "fifo": res["fifo"]["waitSec"]["hot"],
            "priority": res["priority"]["waitSec"]["hot"],
            "floor": res["priority"]["hotCourseHoldSec"],
            "served": [res[p]["served"] == res[p]["parties"] for p in rush.PLANNERS],
        }
        rows.append(row)
        cells = [
            f"{row[k]['median']:>6} / {row[k]['p90']:<5}" for k in ("fifo", "priority", "floor")
        ]
        print(f"{seed:>9} " + " ".join(cells))
    summary: dict[str, Any] = {"seeds": len(rows)}
    for k in ("fifo", "priority", "floor"):
        summary[k] = {s: round(statistics.median(r[k][s] for r in rows), 1) for s in STATS}
    for s in STATS:
        summary[f"priorityBetter_{s}"] = sum(r["priority"][s] < r["fifo"][s] for r in rows)
        summary[f"floorBelowFifo_{s}"] = sum(r["floor"][s] < r["fifo"][s] for r in rows)
    print(
        "median over seeds  "
        + "  ".join(
            f"{k} {summary[k]['median']} / {summary[k]['p90']}"
            for k in ("fifo", "priority", "floor")
        )
    )
    print(
        f"priority beats fifo on {summary['priorityBetter_median']}/{len(rows)} seeds (median), "
        f"{summary['priorityBetter_p90']}/{len(rows)} (p90); the hold floor alone is under fifo "
        f"on {summary['floorBelowFifo_median']} (median), {summary['floorBelowFifo_p90']} (p90)"
    )
    if not all(all(r["served"]) for r in rows):
        print("[fs] warning: some run did not serve every party")
    args.out.mkdir(parents=True, exist_ok=True)
    name = "sweep" + (f"-{args.what_if}" if args.what_if else "") + ".json"
    (args.out / name).write_text(json.dumps({"summary": summary, "seeds": rows}, indent=2) + "\n")
    print(f"[fs] wrote {args.out / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
