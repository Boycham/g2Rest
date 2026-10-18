# Simulator notes

## Full run (numbers of record)

```sh
cd sim && ../backend/.venv/bin/python rush.py      # seed 20261018 from scenario.json, ~3 s
```

Default `RunWeights` (`backend/app/run_weights.py`, untouched), rules routing (no Gemini key),
2 servers + the manager from `data/floor.json`. Three backends, same command and seed:

- **A, before #11's fix** (f15306d): a server holding an accepted ORDER / CHECK still counted as
  free for a RUN card.
- **B, after #11** (1b52242, merged): `Store.free_runners()` counts any accepted task as busy.
- **C, this change** (842f79f): (1) free servers the pass is holding for a run get no new floor
  task, neither from the router nor from escalation (`Pass.reserved` -> `TaskBook.held`);
  (2) a run with a plate past the 5-min ceiling leaves with whoever is free, the manager
  included, 3 plates each, the rest on the next free hands.

Re-run on this branch (engine unchanged since C, so C is still current; `rush.py` ~2.9 s):
every number below matches. New row `hot hold floor` (the wait the course rule alone forces, see
"Priority vs FIFO" below): 19.4 / 72.9 s median / p90 at this seed, the same for both planners.

### Seed 20261018

| | FIFO A | FIFO B | FIFO C | priority A | priority B | priority C |
|---|---:|---:|---:|---:|---:|---:|
| **hot course whole at the table, median (s)** | 113 | 98.7 | 98.7 | 87.5 | 87.5 | **91.1** |
| **hot course whole at the table, p90 (s)** | 149 | 140 | 140 | 137 | 170 | **164** |
| **plates over the 5-min ceiling** | 0 | 0 | 0 | 0 | 3 | **0** |
| **idle while reserved (s)** (s1 / s2) | 0 | 0 | 0 | 77 (0 / 77) | 238 (207 / 31) | **337 (252 / 85)** |
| **RUN tasks escalated** | 28 | 3 | 3 | 18 | 2 | **2** |
| floor tasks escalated | 29 | 24 | 24 | 24 | 27 | 28 |
| hot wait at the pass, median / p90 / max (s) | 0.0 / 24.8 / 68.0 | 0.0 / 46.5 / 66.0 | 0.0 / 46.5 / 66.0 | 20.3 / 76.0 / 97.2 | 27.6 / 127 / 331 | 38.1 / 127 / 188 |
| hot plate to table, median / p90 (s) | 90.8 / 148 | 86.2 / 133 | 86.2 / 133 | 123 / 175 | 101 / 200 | 114 / 196 |
| RUN trips (manager's) | 106 (22) | 92 (1) | 92 (1) | 63 (10) | 63 (0) | 63 (0) |
| courses that left together | 21/56 | 21/56 | 21/56 | 56/56 | 56/56 | 56/56 |
| runs pairing 2+ tables | 5 | 8 | 8 | 0 | 0 | 0 |
| parties served | 20/20 | 20/20 | 20/20 | 20/20 | 20/20 | 20/20 |

`out/rush-20261018.json` has every number of the current run (C) plus the full event streams.
FIFO is identical in B and C: its runs need one runner, so it never reserves anyone and, in
this scenario, never has a plate past the ceiling.

### Seed sweep (seeds 1-20, same scenario)

Median over the 20 seeds of each run's number (`sweep.py`, which calls `rush.offline`):

| | FIFO A | FIFO B | FIFO C | priority A | priority B | priority C |
|---|---:|---:|---:|---:|---:|---:|
| **hot course whole at the table, median (s)** | 113 | 104 | 104 | 88.4 | 88.6 | **87.4** |
| **hot course whole at the table, p90 (s)** | 175 | 149 | 149 | 150 | 156 | **156** |
| **plates over the ceiling, all seeds (seeds with any)** | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 18 (4) | **0 (0)** |
| **idle while reserved (s)** | 0 | 0 | 0 | 76.5 | 280 | **303** |
| **RUN tasks escalated** | 27 | 6 | 6 | 16 | 4 | **4** |
| floor tasks escalated | 28 | 30.5 | 30.5 | 24 | 25 | 25 |
| hot wait at the pass, median / p90 / max (s) | 0.1 / 47.0 / 70.1 | 11.3 / 56.7 / 82.9 | 11.3 / 56.7 / 82.9 | 17.3 / 68.7 / 106 | 28.4 / 110 / 198 | 28.4 / 119 / 165 |
| RUN trips (manager's) | 104 (18.5) | 97.5 (4) | 97.5 (4) | 66.5 (9.5) | 67 (3) | 66.5 (2) |

| priority better than FIFO on ... (seeds of 20) | A | B | C |
|---|---:|---:|---:|
| **hot course at the table, median** | 20 | 19 | **19** |
| **hot course at the table, p90** | 14 | 5 | **5** |
| hot pass wait, median | 0 | 1 | 1 |
| hot pass wait, p90 | 2 | 0 | 0 |

Every run served 20/20 parties.

## What this change did (honest reading)

- **The ceiling rule works:** no plate over 5 minutes on any seed (18 plates over 4 seeds in B),
  and priority's worst hot pass wait, median over seeds, fell from 198 s to 165 s.
- **Holding reserved servers works where it was aimed:** at seed 20261018 T4's four-plate mains
  no longer wait 331 s; the worst hot plate now waits 188 s and nothing reaches the ceiling, so
  rule 2 never had to fire there. That run's server is kept free while the second one finishes.
- **It does not close the p90 gap.** Whole course at the table, p90 over seeds: 150 s (A),
  156 s (B), 156 s (C); priority still beats FIFO at p90 on only 5 of 20 seeds (14 in A). The
  median is unchanged in practice (88.6 -> 87.4 s, 19/20 seeds).
- **Costs:** idle while reserved rises (280 -> 303 s over seeds, 238 -> 337 s at the headline
  seed), by design: a held server waits with empty hands instead of taking floor work. Floor work
  that would have gone to them queues on the other server, and floor escalations are flat (25).
  At seed 20261018 a few things got worse: hot pass-wait median 27.6 -> 38.1 s and course at the
  table median 87.5 -> 91.1 s; p90 improved 170 -> 164 s.
- **Why A still has the best p90 (inference, not measured directly):** in A the pass handed RUN
  cards to servers who were mid-order; those escalated, and the manager ended up carrying about
  9.5 runs a night as an extra pair of hands. Since #11 the manager only runs food past the
  ceiling (2 trips a night in C), so a big course gets its second runner only from the two
  servers. Letting the manager take the second half of a big course earlier than the ceiling
  (say past 2-3 minutes) is the obvious next experiment; not done here.

## Priority vs FIFO on hot-plate wait at the pass: the course rule makes it impossible

Asked: make priority beat FIFO on median and p90 hot-plate pass wait (`pass.up` to `pass.run`)
at seed 20261018 and over seeds 1-20, without breaking the build plan's rules. **It can't be done
while "a table's whole course goes out together" holds**, so the engine is unchanged. Numbers:

```sh
cd sim && ../backend/.venv/bin/python rush.py                                  # seed 20261018
cd sim && ../backend/.venv/bin/python sweep.py                                 # seeds 1-20, ~35 s
cd sim && ../backend/.venv/bin/python sweep.py --what-if no-course-hold        # experiment only
```

**The hold floor.** A course is ready only when its last plate is up, so each hot plate waits at
least from its own `pass.up` to the last `pass.up` of its course (`hotCourseHoldSec`, printed as
"hot hold floor"). That gap is the kitchen's per-plate jitter (up to 90 s for mains in
`scenario.json`), drawn from the seed: it is identical under both planners on every seed
(checked: the per-plate lists are equal), so no planner that keeps courses together can go
below it, even with unlimited instant runners. Percentiles of a per-plate lower bound are lower
bounds of the percentiles.

| hot pass wait, median / p90 (s) | FIFO | priority (now) | hold floor (any course-together planner) |
|---|---:|---:|---:|
| seed 20261018 | **0.0 / 46.5** | 38.1 / 127 | **19.4 / 72.9** |
| seeds 1-20, median over seeds | **11.3 / 56.7** | 28.4 / 119 | **11.5 / 55.3** |
| seeds where it is under FIFO (median / p90) | | 1 / 0 of 20 | 10 / 12 of 20 |

- Seed 20261018: the floor is above FIFO on both numbers (19.4 > 0.0, 72.9 > 46.5). Impossible.
- Sweep median: floor 11.5 s > FIFO 11.3 s. Impossible.
- Sweep p90: floor 55.3 s vs FIFO 56.7 s leaves 1.4 s for everything else (reaction is not in
  the metric, but a free server must exist the instant the last plate lands, for 90% of hot
  plates, through a rush with two servers). Not reachable in practice; priority's after-course-up
  p90 is 76-157 s per seed today.

**What the rule costs, measured** (what-if, plates may leave as they come up; breaks the rule,
not shipped): priority drops to 13.9 / 68.8 s over seeds (11.4 / 56.2 s at 20261018), still
behind FIFO's 11.3 / 56.7 (better on 5 and 2 seeds of 20), and courses left together fall from
~55/56 to ~22/56. So the course rule explains most of the gap; the rest is below.

**Where priority's wait beyond the floor comes from** (seeds 1-20, hot plates by course size):

| course size | share of hot plates | priority wait median / p90 | of it after course up | FIFO wait median / p90 |
|---|---:|---:|---:|---:|
| 1 plate | 5% | 0.0 / 42.1 | 0.0 / 42.1 | 0.0 / 50.0 |
| 2-3 plates | 48% | 14.0 / 63.0 | 0.0 / 36.6 | 3.5 / 51.8 |
| 4+ plates | 47% | 57.3 / 139 | 22.5 / 93.2 | 18.2 / 58.6 |

- **Runner limit (3 plates) + two servers:** a 4+ plate course needs two free servers at once, and
  half the hot plates are in such courses. Their after-course-up p90 is 93 s (FIFO's plates 47 s);
  this is where priority's p90 goes. The reservation (`Pass.reserved`, idle while reserved
  ~300 s a night) keeps it under the ceiling but can't create a second pair of hands.
- **2-3 plate courses** leave as soon as they are whole (after-course-up median 0) and beat FIFO
  after course up at p90 (36.6 vs 47.8 s); their total is the hold.
- **Scoring weights and course above temperature** only decide which ready course goes first when
  hands are short; with the hold in place they can't lower the floor, and dropping the hold
  (what-if) still leaves priority behind FIFO because a cold appetizer course (12) outranks a hot
  main (11) by design.
- **Pairing** (0 cross-table runs) and **cold never delays hot** don't bind here: cold plates
  never ride with another table's hot run, and pairing only uses spare hands.
- **The 5-min ceiling** fires on no seed (0 plates over), so it adds no wait.

**What would change the answer (team's call, each changes a rule or the model):**
1. Measure from the course being whole, not per plate (`hot wait after course up`, `hot course
   whole at the table`): priority already wins the guest-facing median (87 vs 104 s, 19/20 seeds).
2. Let the kitchen fire a course to come up together (cook-time staggering): the hold floor is
   kitchen timing, so this is a kitchen/model change, not a dispatch change.
3. The manager (or a third server) as an earlier second pair of hands for 4+ plate courses: cuts
   the after-course-up tail, but even at zero the floor keeps the median at or above FIFO.

For the demo, keep quoting pass wait as a trade: lead with "course at the table, median" and
"trips", and say that big courses wait for the whole course and for two free servers.

## Surprises and things worth fixing (team's call, not changed here)

- **Big courses still wait for two servers** (see above): the manager as an earlier second pair
  of hands is the next thing to measure.
- **Servers only running food never stress the pass.** The first cut modelled runners alone:
  8 tables keep two runners about a third busy, nothing queues, and the planners differ only by
  the course hold. Real floor work (orders, checks, resets) is what makes it a rush, so it is in
  the model as real tasks.
- **Priority paired no plates across tables (FIFO 8).** Cross-table pairing only fills spare
  hands of a run whose lead is hot, with other all-hot courses that are ready at that same
  instant in the same section. The pass re-plans on every plate, so a ready course leaves as soon
  as anyone is free and rarely meets another one. Left as a design question for the team.
- Task and order ids are random uuids, so event streams differ in ids between runs; times, event
  order and every metric are identical for a seed (`tests/test_engine.py`).

## Live mode check (before the fix)

Backend started as in README (`--speed`-scaled timers, no Gemini), then
`rush.py --live --speed 200 --planners priority`: 20/20 parties, hot pass wait median / p90 /
max 19.4 / 73.0 / 84.2 s (offline then 20.3 / 76.0 / 97.2), course at table median 87.6 s, 49/56
courses together (the compressed real-clock timing splits a few). About 75 s per planner at
x200, about 3 min at the default x80. Not rerun after the fix; not watched in the browser pages.

## Model limits

- Fictional service; cook, eating and walking ranges are guesses, not measured on a floor.
- One task per person at a time; RUN cards jump queued floor work but never interrupt a task.
- Tables are not pushed together; 5-6 tops wait for one of the two 6-tops.
- `pass.run` is when the pass hands the run to a server, not when the plates are lifted;
  "plate to table" covers the rest.
