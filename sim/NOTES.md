# Simulator notes

## Full run (numbers of record)

```sh
cd sim && ../backend/.venv/bin/python rush.py      # seed 20261018 from scenario.json, ~3 s
```

Default `RunWeights` (`backend/app/run_weights.py`, untouched), rules routing (no Gemini key),
2 servers + the manager from `data/floor.json`. Seed `20261018`, before and after the
`Store.free_runners()` fix (1f6cba8: a server with an accepted ORDER / CHECK / CLEAR / SEAT task
no longer counts as free for a RUN card):

| | FIFO before | FIFO after | priority before | priority after |
|---|---:|---:|---:|---:|
| parties served | 20/20 | 20/20 | 20/20 | 20/20 |
| **hot wait at the pass, median / p90 / max (s)** | 0.0 / 24.8 / 68.0 | **0.0 / 46.5 / 66.0** | 20.3 / 76.0 / 97.2 | **27.6 / 127 / 331** |
| warm wait median / p90 / max (s) | 0.0 / 5.4 / 19.5 | 18.9 / 55.0 / 77.3 | 0.0 / 29.4 / 59.2 | 0.0 / 32.7 / 45.0 |
| room wait median / p90 / max (s) | 0.0 / 30.4 / 47.3 | 21.1 / 53.1 / 59.1 | 0.0 / 23.5 / 26.5 | 1.3 / 65.4 / 105 |
| cold wait median / p90 / max (s) | 0.0 / 26.4 / 55.8 | 4.5 / 65.2 / 86.6 | 0.0 / 39.0 / 67.5 | 23.2 / 113 / 246 |
| hot plate to table, median / p90 (s) | 90.8 / 148 | 86.2 / 133 | 123 / 175 | 101 / 200 |
| hot wait after its course was all up, p90 (s) | 16.8 | 35.9 | 9.6 | 93.6 |
| **hot course whole at the table, median / p90 (s)** | 113 / 149 | **98.7 / 140** | 87.5 / 137 | **87.5 / 170** |
| plates over the 5-min ceiling (hot) | 0 | 0 | 0 | 3 (3) |
| runs pairing 2+ tables | 5 | 8 | 0 | 0 |
| RUN trips (manager's) | 106 (22) | 92 (1) | 63 (10) | 63 (0) |
| RUN tasks escalated | 28 | 3 | 18 | 2 |
| floor tasks escalated | 29 | 24 | 24 | 27 |
| courses that left together | 21/56 | 21/56 | 56/56 | 56/56 |
| idle while reserved: total (s1 / s2) | 0 | 0 | 77 (0 / 77) | 238 (207 / 31) |
| service end (min) | 242 | 238 | 248 | 239 |

`out/rush-20261018.json` has every number of the current run plus the full event streams.
"Before" is the same command at f15306d.

## What the fix did

- **Escalations and the manager:** RUN escalations fell from 28 to 3 (FIFO) and 18 to 2
  (priority); the manager ran 1 and 0 trips instead of 22 and 10. Cards now go to someone who
  can take them, so the 30 s escalation no longer stands in for "server is busy".
- **FIFO got better for the guests:** fewer trips (92 vs 106), hot plate to table median 86 s
  (was 91), whole hot course at the table median 99 s (was 113). Its pass-wait p90 rose because
  plates now wait at the pass for a free server instead of waiting on a card nobody accepted;
  the old pass wait hid that time inside "plate to table".
- **Priority got worse on the long tail:** hot pass-wait p90 127 s (was 76), max 331 s, and 3
  hot plates over the 5-minute ceiling, all one course: T4's four-plate mains (a 5-top). A course
  of 4+ plates needs two runners (max 3 plates each), and they must be free at the same moment.
  In the trace from 10468 s to 10732 s s1 and s2 take turns being free; every time one is free
  the router hands them a new CLEAR, ORDER or CHECK card, which they accept within seconds, so
  both are never free together until 331 s. Before the fix a server holding an order still counted as
  free, so "two free" happened sooner (and then one card escalated to the manager). The ceiling
  bonus can only move a run to the top of the list; it can't give it a second pair of hands.
  Idle-while-reserved rose from 77 s to 238 s, and all of it is now empty-handed (a free server
  is by definition not holding accepted work).

## Priority still does not beat FIFO on hot-plate wait at the pass

Measured as asked (`pass.up` to `pass.run`, per plate), priority is worse at this seed (hot
median 27.6 s vs 0.0 s, p90 127 s vs 46.5 s) and on 19 of 20 seeds (below). The weights were
not tuned; besides the clock hook, the fix above is the only backend change.

Why: "a table's whole course goes out together". A course is only ready when its last plate is
up, so its first hot plate waits for the slowest one (the per-plate kitchen spread here is up to
90 s for mains), and a 4+ plate course also waits for two free servers. FIFO sends each plate
as soon as someone is free, so its per-plate pass wait stays low, but tables get their course in
pieces (21 of 56 courses left together, up to 89 s p90 between first and last plate).

What guests see still favours priority at the median: kitchen finishing a hot course to the whole
table having it, 87.5 s vs 98.7 s at this seed and on 19/20 seeds. At p90 it is now worse (170
vs 140 s here, better on only 5/20 seeds) because of the two-runner waits above. Priority still
makes about a third fewer trips.

For the demo, quote pass wait as a trade: lead with "course at the table, median" and "trips",
and say that big courses can wait for two free servers.

## Seed sweep (seeds 1-20, same scenario)

Median over the 20 seeds of each run's number (offline, `rush.offline(scn, seed, ...)`):

| | FIFO before | FIFO after | priority before | priority after |
|---|---:|---:|---:|---:|
| hot wait at the pass, median (s) | 0.1 | 11.3 | 17.3 | 28.4 |
| hot wait at the pass, p90 (s) | 47.0 | 56.7 | 68.7 | 110 |
| hot wait at the pass, max (s) | 70.1 | 82.9 | 106 | 198 |
| hot plate to table, median (s) | 101 | 93.3 | 103 | 109 |
| hot course whole at table, median (s) | 113 | 104 | 88.4 | 88.6 |
| hot course whole at table, p90 (s) | 175 | 149 | 150 | 156 |
| RUN trips (manager's) | 104 (18.5) | 97.5 (4) | 66.5 (9.5) | 67 (3) |
| RUN tasks escalated | 27 | 6 | 16 | 4 |
| idle while reserved (s) | 0 | 0 | 76.5 | 280 |
| runs pairing 2+ tables | 7 | 7 | 0 | 0 |

| priority better than FIFO on ... (seeds of 20) | before | after |
|---|---:|---:|
| hot pass wait, median | 0 | 1 |
| hot pass wait, p90 | 2 | 0 |
| hot course at the table, median | 20 | 19 |
| hot course at the table, p90 | 14 | 5 |

5-minute ceiling: before, 0 plates on any seed for either planner. After, FIFO 0; priority 18
plates over 4 seeds. Every run served 20/20 parties.

## Surprises and things worth fixing (team's call, not changed here)

- **Big courses wait for two servers at once** (above). Options to measure: let the manager count
  as a runner for the second pair of hands, keep a reserved free server off new floor cards for a
  short while, or split a course that has waited past some limit.
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
