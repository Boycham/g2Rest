# Dinner-rush simulator (step 9)

Replays a fictional two-hour Saturday service on the real backend (`Store`, `Hub`, the pass and
its planners, `TaskBook` escalation, the rules router), once with the FIFO planner and once with
priority scoring, and prints the hot-plate wait at the pass side by side. Numbers and what they
mean: [NOTES.md](NOTES.md).

```sh
cd sim && ../backend/.venv/bin/python rush.py          # both planners, offline, ~3 s
../backend/.venv/bin/python rush.py --seed 7           # another service, same shape
../backend/.venv/bin/python sweep.py                   # seeds 1-20 side by side, ~35 s
../backend/.venv/bin/python -m pytest -q tests         # metrics, a tiny service, the mock servers
```

Priority does not beat FIFO on per-plate hot pass wait and can't while a course leaves whole:
the hold floor alone is above FIFO's median (see NOTES.md, "Priority vs FIFO"). It does win
the guest-facing number, hot course whole at the table.

It writes `out/rush-<seed>.json` (the same table, per planner) and one
`out/rush-<seed>-<planner>-events.jsonl` with every event stamped in simulated seconds. `out/` is
gitignored.

## How it works

- **Scenario** (`scenario.json`, seed `20261018`): 20 parties arrive over 120 min, peaking in the
  middle (1, 2, 3, 4, 4, 3, 2, 1 per quarter hour), sizes 2-6, seated at the smallest free table
  that fits (2-, 4- and 6-tops from `data/floor.json`, waitlist otherwise). Dishes come from
  `data/menu.json`: 60% of guests take an appetizer, everyone a main, 50% a dessert. Cook and
  eating times per course are ranges in the file; `scenario.py` draws every guest and kitchen
  duration once from the seed, so both planners serve exactly the same night.
- **Offline clock**: `Store.from_settings(..., clock=FakeClock)` (the hook in
  `backend/app/state.py`). A heap of timed callbacks plus the backend's 1 s ticker (escalation,
  overdue reroute, re-plan) advance it; nothing sleeps. `GEMINI_API_KEY` is removed and
  `Settings(gemini_api_key="")` is used, so routing is the rules.
- **Floor staff** (`engine.Runner`, one per server plus the manager) hold one task at a time;
  other cards queue on the "glasses", a RUN ahead of floor work. After a reaction time (3-12 s,
  5% slow at 20-45 s) they send `task.accept`, keep the task open for its work time and only then
  send `task.done`, which frees them for the pass. RUN work time is travel 45-90 s + 15 s per
  extra table on the card.
- **Floor work** goes through `POST /tasks` routing like on the night: an ORDER task when a table
  is ready to order (its order is fired when the task is done), an ORDER "dessert order" task, a
  CHECK task to pay and a CLEAR task before the table can be seated again. A card that sits
  unaccepted 30 s because its server is busy escalates (next server, then the manager).
- **Kitchen**: plates go up per course at the drawn cook time plus a per-plate jitter
  (`POST /pass/up` path: `store.plate_up` then `hub.replan`). Mains are timed off the appetizers
  reaching the table, desserts off the dessert order.

## Metrics (`metrics.py`, from the event stream only)

| Row | Definition |
|---|---|
| wait median / p90 / max | `pass.up` to `pass.run` per plate (nearest-rank), split by the dish's temperature |
| plate to table | `pass.up` to `task.done` of the RUN that carried it |
| hot hold floor | per hot plate, its `pass.up` to the last `pass.up` of its course: the wait the "whole course goes out together" rule alone forces, the same for every planner (kitchen jitter only), so a lower bound for priority |
| hot wait after course up | hot plate's wait counted from the last plate of its course coming up |
| hot course whole at table | per course with a hot plate: last plate up to last plate delivered |
| over 5 min ceiling | plates with a pass wait above 300 s (`RunWeights.ceiling_min`) |
| runs pairing 2+ tables | runs whose plates belong to two or more tables |
| idle while reserved | seconds a server the pass counted free (no open RUN, no accepted task) sat while the best ready run waited for more hands than were free; total, per server, and how much of it the server was empty-handed (not holding accepted floor work) |

Reservation spans are recorded by the simulator as `sim.reserved {idle, busy, runners, plates}`
each time the set changes, after every event and tick (the pass re-plans on every event, so a
ready run with a free server still waiting means it is held for more hands).

## Mock servers for the routing demo (`mock_staff.py`)

The owner wears the real G2 as `s1` (Ava). `mock_staff.py` puts the other servers on the floor so
the router (Gemini, or the rules) has someone to choose between and the manager dashboard shows
them working. Each mock opens the same staff socket as the glasses
(`/ws?token=&role=server&staff=s2`), so it is in `GET /health` `online` and the router can pick
it; it answers its cards with the real `task.accept` / `task.done` / `task.bounce` frames, so
`/stats` (and Gemini's context) times it like a person.

```sh
cd backend && FS_FLOOR=demo FS_TOKEN= .venv/bin/uvicorn app.main:app --port 8787   # 4-server demo floor
cd sim && ../backend/.venv/bin/python mock_staff.py --staff s2,s3,s4 --dispatch-every 20
# another backend: --api http://localhost:8818 --token "$FS_TOKEN" (default: $FS_TOKEN)
```

`FS_FLOOR=demo` loads `data/floor.demo.json`: the record floor's tables with four servers, Ava
(A, the glasses), Ben (B), Cam (C) and Dee (D), every mock covering the other mocks' sections so
escalation has a next server before the manager. `data/floor.json` (Ava and Ben) stays the floor of
record for the rush numbers and the tests.

Per mock, every action is one `[fs-mock]` line (`accept`, `done`, `bounce`, `slow`, `lost`,
`refused`, `online`/`offline`):

- **Accept** a `task.assigned` after 3-10 s (`--accept-sec 3,10`).
- **Done** after a kind-based work time: RUN 20-40 s, CHECK 15 s, CLEAR 20-30 s, ORDER 30-50 s,
  SEAT 10-20 s, times the mock's speed: Ben x0.7, Cam x1, Dee x1.4 by default (`--speed
  s2=0.7,s4=1.5`), so `/stats` `avgSecByKind` really differs between them.
- **Bounce** 15% of new cards before accepting (`--bounce-share`), never the same card twice, so the
  router re-routes it.
- **Slow** on 10% of tasks (`--slow-share`): holds it `doneSec` + 15 s (the backend's `GET /stats`
  `doneSec`, `FS_DONE_SEC`), so the manager gets the "not done" alert and the backend reroutes it
  (a RUN is only flagged).
- **Lost / refused**: a card taken away from the mock (`task.updated` `bounced` after an
  escalation, a slow-task reroute or a manager reroute) or closed elsewhere (`done`) cancels its
  timer; a `task.rejected` is logged as `refused` and the card dropped.
- `--time-scale 0.2` shortens every wait for a quick check; `--seed` makes a run repeatable.

`--dispatch-every N` posts a demo task (CHECK, CLEAR, ORDER, SEAT or a RUN of one menu dish) every
N seconds through `POST /tasks` without an assignee, so the router picks the server and the
routing log keeps moving. It only uses the mocks' own tables (C and D on the demo floor, or
`--tables T3,T7`). The mocks never open `s1`'s socket (`--staff s1` is refused) and never act on a
card assigned to `s1`: if the router (or an escalation) gives Ava a task, it is a real card on the
real glasses, logged as `-> Ava (the real glasses)`.

Ctrl-C closes every socket (the mocks drop out of `/health` `online` at once and their open cards
follow the backend's offline escalation). A dropped socket reconnects every 2 s.

## --live (demo)

Drives a running backend over HTTP and WebSocket so the Organizer and Kitchen pages show the
rush. At the default `--speed 80` one planner's service (about 250 simulated minutes, waitlist
included) takes about 3 minutes. The backend runs on its real clock, so scale its timers by the
same factor and keep Gemini off:

```sh
cd backend && GEMINI_API_KEY= FS_TOKEN= FS_ESCALATION_SEC=0.375 FS_OFFLINE_ESCALATION_SEC=1.5 \
  FS_DONE_SEC=3.75 .venv/bin/uvicorn app.main:app --port 8787
cd sim && ../backend/.venv/bin/python rush.py --live --planners priority   # or fifo,priority
```

`POST /reset` runs before each planner. Live numbers are approximate (HTTP round trips cost
simulated time; RunWeights decay and the ceiling stay in real minutes; idle-while-reserved isn't
measured); the offline run is the one to quote.
