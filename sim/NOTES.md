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

Median over the 20 seeds of each run's number (`out/sweep.py` calling `rush.offline`):

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

## Priority still does not beat FIFO on hot-plate wait at the pass

Measured as asked (`pass.up` to `pass.run`, per plate), priority is worse at this seed (hot
median 38.1 s vs 0.0 s, p90 127 s vs 46.5 s) and on 19 of 20 seeds. The weights were not tuned.

Why: "a table's whole course goes out together". A course is only ready when its last plate is
up, so its first hot plate waits for the slowest one (the per-plate kitchen spread here is up to
90 s for mains), and a 4+ plate course also waits for two free servers. FIFO sends each plate
as soon as someone is free, so its per-plate pass wait stays low, but tables get their course in
pieces (21 of 56 courses left together, up to 89 s p90 between first and last plate).

What guests see still favours priority at the median: kitchen finishing a hot course to the whole
table having it, 87.4 s vs 104 s over seeds (19/20 seeds), with about a third fewer trips. At
p90 it is worse (156 vs 149 s over seeds, better on 5/20).

For the demo, quote pass wait as a trade: lead with "course at the table, median" and "trips",
and say that big courses can wait for two free servers.

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
