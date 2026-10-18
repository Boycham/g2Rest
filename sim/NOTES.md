# Simulator notes

## Full run (numbers of record)

```sh
cd sim && ../backend/.venv/bin/python rush.py      # seed 20261018 from scenario.json, ~3 s
```

Backend at this branch, default `RunWeights` (`backend/app/run_weights.py`, untouched), rules
routing (no Gemini key), 2 servers + the manager from `data/floor.json`. Seed `20261018`:

| | FIFO | priority |
|---|---:|---:|
| parties served | 20/20 | 20/20 |
| plates (hot) | 118 (66) | 118 (66) |
| **hot wait at the pass, median / p90 / max (s)** | **0.0 / 24.8 / 68.0** | **20.3 / 76.0 / 97.2** |
| warm wait median / p90 / max (s) | 0.0 / 5.4 / 19.5 | 0.0 / 29.4 / 59.2 |
| room wait median / p90 / max (s) | 0.0 / 30.4 / 47.3 | 0.0 / 23.5 / 26.5 |
| cold wait median / p90 / max (s) | 0.0 / 26.4 / 55.8 | 0.0 / 39.0 / 67.5 |
| hot plate to table, median / p90 (s) | 90.8 / 148 | 123 / 175 |
| hot wait after its course was all up, p90 (s) | 16.8 | 9.6 |
| **hot course whole at the table, median / p90 (s)** | **113 / 149** | **87.5 / 137** |
| plates over the 5-min ceiling | 0 | 0 |
| runs pairing 2+ tables | 5 | 0 |
| RUN trips (manager's) | 106 (22) | 63 (10) |
| RUN tasks escalated | 28 | 18 |
| courses that left together | 21/56 | 56/56 |
| idle while reserved: total (s1 / s2) | 0 (0 / 0) | 77 (0 / 77) |
| of it empty-handed | 0 | 68 |

`out/rush-20261018.json` has every number above plus the full event streams.

## Priority does not beat FIFO on hot-plate wait at the pass

Measured as asked (`pass.up` to `pass.run`, per plate), priority is worse: hot median 20.3 s vs
0.0 s, p90 76 s vs 25 s. It is the same on every seed tried (20/20 seeds, below). The weights
were not tuned; nothing in `backend/` changed except the clock hook.

Why: the main cost is the rule "a table's whole course goes out together". A course is only
ready when its last plate is up, so the first hot plate of a four-top's mains waits at the pass
for the slowest one (the kitchen's per-plate spread here is up to 90 s for mains). FIFO sends
every plate the moment a server is free, so its per-plate pass wait is near zero, but the table
gets its course in pieces: only 21 of 56 courses left together, with up to 85 s (p90) between
the first and the last plate of one course. Counting a hot plate's wait only from the moment
its course was all up, priority is better (p90 9.6 s vs 16.8 s).

What the guests see favours priority: from the kitchen finishing a hot course to the whole table
having it, median 87.5 s vs 113 s (p90 137 vs 149), on 20/20 seeds for the median. Priority also
does it in 63 trips instead of 106, and escalates fewer RUN cards (18 vs 28) because fewer cards
land on busy servers.

So for the demo, quote pass wait honestly as a trade, and lead with "course at the table" and
"trips": per-plate pass wait is FIFO's best case by construction.

## Seed sweep (seeds 1-20, same scenario)

Median over the 20 seeds (offline, `rush.offline(scn, seed, ...)`):

| | FIFO | priority |
|---|---:|---:|
| hot wait at the pass, median (s) | 0.1 | 17.3 |
| hot wait at the pass, p90 (s) | 47.0 | 68.7 |
| hot plate to table, median (s) | 101 | 103 |
| hot course whole at table, median (s) | 113 | 88.4 |
| hot course whole at table, p90 (s) | 175 | 150 |
| RUN trips | 104 | 66.5 |
| RUN tasks escalated | 27 | 16 |
| idle while reserved (s) | 0 | 76.5 |
| plates over 5 min | 0 | 0 |

Priority had the lower hot pass-wait median on 0/20 seeds, the lower course-at-table median on
20/20 and the lower course-at-table p90 on 14/20.

## Surprises and things worth fixing (Coder A's call, not changed here)

- **Servers only running food never stress the pass.** The first cut modelled runners alone:
  8 tables keep two runners about a third busy, nothing queued, and the planners differed only by
  the course hold. Real floor work (orders, checks, resets) is what makes it a rush, so it is in
  the model as real tasks.
- **`Store.free_runners()` only looks at open RUN tasks.** A server taking a 2-3 minute order is
  "free" to the pass, gets the RUN card, can't accept it, and it escalates 30 s later (28 FIFO / 18
  priority RUN escalations; the manager ends up running 10-22 trips). Counting accepted ORDER
  and CHECK tasks as busy, or preferring the server with no accepted task, would likely cut both.
  Of priority's 77 s idle-while-reserved, 68 s was truly empty-handed; the other 9 s the "free"
  server was holding floor work.
- **Priority paired no plates across tables (FIFO 5).** Cross-table pairing only fills spare
  hands of a run whose lead is hot, with other all-hot courses that are ready at that same
  instant in the same section. The pass re-plans on every plate, so a ready course leaves as soon
  as anyone is free and rarely meets another one. Pairing would need a short hold, which costs
  wait; worth measuring before building.
- **No plate reached the 5-minute ceiling** in either planner on any seed, so the ceiling bonus is
  never exercised by this service; a heavier scenario (more parties, one server) would test it.
- Task and order ids are random uuids, so event streams differ in ids between runs; times, event
  order and every metric are identical for a seed (`tests/test_engine.py`).

## Live mode check

Backend started as in README (`--speed`-scaled timers, no Gemini), then
`rush.py --live --speed 200 --planners priority`: 20/20 parties, hot pass wait median / p90 /
max 19.4 / 73.0 / 84.2 s (offline 20.3 / 76.0 / 97.2), course at table median 87.6 s, 49/56
courses together (the compressed real-clock timing splits a few). It plays about 75 s per
planner at x200, about 3 min at the default x80. Not watched in the browser pages this session.

## Model limits

- Fictional service; cook, eating and walking ranges are guesses, not measured on a floor.
- One task per person at a time; RUN cards jump queued floor work but never interrupt a task.
- Tables are not pushed together; 5-6 tops wait for one of the two 6-tops.
- `pass.run` is when the pass hands the run to a server, not when the plates are lifted;
  "plate to table" covers the rest.
