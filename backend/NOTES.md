# Backend notes (restaurant brain, Coder A lane)

What was verified, how to run it, and what is still open. Numbers are from the dev VM, not hardware.

## Run it

```sh
cd backend
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/ruff check app tests scripts mock && .venv/bin/python -m pytest -q      # 70 passed
FS_TOKEN= .venv/bin/uvicorn app.main:app --port 8787                              # empty token = open dev mode
```

Environment: `FS_TOKEN` (shared HTTP + WebSocket token; empty = no auth, for local dev only),
`FS_ESCALATION_SEC` (default 30), `FS_PORT`, `FS_DATA_DIR` (default `../data`),
`GEMINI_API_KEY` (empty = the router uses the rules only), `FS_GEMINI_MODEL` (default
`gemini-3.1-flash-lite`), `FS_ROUTER_TIMEOUT_SEC` (default 1.5), `FS_DONE_SEC` (default 300: an
accepted task held this long alerts the manager and is rerouted, RUN tasks alert only).

## Task router (`app/router.py`)

`POST /tasks` without `assignee` asks Gemini who should take the task: one call with the task, its
table's section and every server's open tasks (with `heldSec`) and average accept-to-done time per
task kind (`GET /stats`), answer constrained to the server ids. Any error, a
timeout or no key falls back to the rule pick (the section's server). Each pick lands in the event
log as `router.pick {assignee, rule, how: gemini|rules, ms}`; `ms` is the number to watch on stage.
Escalation, bounces and RUN tasks from the pass stay on the rules.

Measured Oct 18 from the dev Mac, `gemini-3.1-flash-lite`, six picks: 1043 ms (first, cold), then
506-715 ms. Twenty more with a 5 s cap and the fuller context: median 826 ms, p90 2206 ms, max
3149 ms, hence the 3 s default. Then the free-tier key hit `429 RESOURCE_EXHAUSTED` after about 50
calls and every pick fell back to the rules: the demo needs a billed key or few test calls before it.
The key goes in `?key=`: AI Studio's `AQ.` keys get a 404 with the `x-goog-api-key` header.

## Sync 1 check: the real glasses app against this server (for Coder B)

The glasses app defaults to `ws://localhost:8787/ws`, the same port as `fake-backend.ts`, so nothing
in `glasses/` needs to change. Do **not** start `fake-backend.ts`.

```sh
# terminal 1: backend, open dev mode, 30 s escalation
cd backend && FS_TOKEN= .venv/bin/uvicorn app.main:app --port 8787

# terminal 2: glasses app (role=server, staff=s1 by default). Also works with
#   VITE_BACKEND_URL="ws://localhost:8787/ws?role=server&staff=s1" npm run dev
cd glasses && npm run dev
# open the simulator / WebView on http://localhost:5173

# terminal 3: create a task for s1's section (T1-T4 are section A = s1)
curl -s -X POST localhost:8787/tasks -H 'content-type: application/json' \
  -d '{"kind":"RUN","table":"T2","items":[{"qty":2,"dish":"halibut","seats":[1,3]}],
       "allergies":[{"allergen":"SHELLFISH","seats":[3]}]}'
# glasses: tap = task.accept, tap again = task.done. Watch terminal 1 for:
#   [fs] ws open role=server staff=s1 ...   and the event log:
curl -s 'localhost:8787/events?type=task.' | python3 -m json.tool | grep '"to"'
#   -> "queued", "sent", "accepted", "done"
```

With `FS_TOKEN=dev` set, use `VITE_BACKEND_URL="ws://localhost:8787/ws?token=dev"` (the token ends up
in the WebView bundle either way; see the G2 skill, 04-ARCHITECTURE).

Since Sync 1 the glasses build the query themselves: `VITE_FS_TOKEN` (= `FS_TOKEN`) and the role picker give
`?token=&role=&staff=`. **Voice:** `app/voice_bridge.py` dials `VOICE_RELAY_URL` (default
`ws://localhost:8790/ws`, i.e. `backend/voice/relay.py`) on the first `capture.start` of a glasses socket and
forwards capture.* JSON, audio frames and taps on relay orders; a relay draft marked `sent` is written into
`store.orders` with `tool_add_item` / `tool_set_allergy`, fired through `hub.after_fire` (organizer, kitchen)
and answered with `order.closed`. No relay: VOICE OFFLINE on the glasses within 3 s. Tasks queued for an
offline server escalate after `FS_OFFLINE_ESCALATION_SEC` (default 120).

The mock server (step 0) is still there for contract-only work:
`.venv/bin/python mock/mock_server.py` replays `mock/script.json` on the same port.

## Verified

### Task lifecycle, bounce, escalation (step 3 "done" check)

`scripts/task_walkthrough.py` opens sockets for s1, s2 and the manager against a live server
(`FS_ESCALATION_SEC=2`) and checks every state. Output on the dev VM:

```
[fs-walk]   0.17s s1   <- task.assigned task-841c3f assigned
[fs-walk]   0.17s s1   -> task.accept
[fs-walk]   0.17s s1   <- task.updated task-841c3f accepted
[fs-walk]   0.17s s1   -> task.done
[fs-walk]   0.17s s1   <- task.updated task-841c3f done
[fs-walk]   0.17s s1   <- task.assigned task-271ba0 assigned
[fs-walk]   0.17s s1   -> task.bounce
[fs-walk]   0.17s s1   <- task.updated task-271ba0 bounced
[fs-walk]   0.17s s2   <- task.assigned task-271ba0 assigned
...
[fs-walk]   0.17s s1   <- task.assigned task-ae43c5 assigned
[fs-walk]   2.31s s1   <- task.updated task-ae43c5 bounced        (2 s after sent, nobody accepted)
[fs-walk]   2.31s s2   <- task.assigned task-ae43c5 assigned
[fs-walk]   4.31s s2   <- task.updated task-ae43c5 bounced
[fs-walk]   4.31s m1   <- task.assigned task-ae43c5 assigned
[fs-walk]   6.31s m1   <- alert {"id": "unacked-task-ae43c5", "level": "urgent", ...}
[fs-walk]   6.31s m1   -> task.done
[fs-walk]   6.31s m1   <- alert {... "cleared": true}
[fs-walk]   6.32s chk  PASS happy path / bounce / escalation chain / alert raised and cleared / event log append-only
```

Escalation timer: starts at `sent` (the card went down the assignee's socket), stops at `accepted`.
A task `queued` for an offline server is not timed (open question in CONTRACT.md §8.6).
Escalation ticks run every 1 s, so a 30 s timeout fires at 30-31 s.

### Contract

`app/contract.py` mirrors `glasses/src/contract.ts` in pydantic with `extra="forbid"`. Every inbound
frame is parsed with it (bad frames become `ws.rejected` events, the socket stays up), every outbound
frame is checked before `send_text` (an off-contract message is logged `[fs] off-contract ...` and not
sent). `tests/test_contract.py` builds every message type the backend can emit and proves the base
`contract.ts` models still parse them once the backend's extra fields are dropped.

### Run priority (step 4)

`tests/test_runs.py`, all pure functions, clock injected:

- appetizers first (cold appetizer 12 > hot main 11 > hot dessert 7), hot beats cold within a course,
  hot rises 3/min vs cold 1/min
- a table's course waits for its last plate and `holds[].waitingOn` names it
- 5 plates -> one run, two runners; four single hot plates in a section -> one run of 3 + one of 1
- a hot run never waits for a cold plate at another table; a cold plate rides along only for the
  same table and only if already up
- any plate up > 5 min goes to the top (`ceiling_bonus`)
- FIFO baseline: plates leave strictly in up order, three at a time, no course hold
- all numbers in `app/run_weights.py::RunWeights`, round-trip through `to_dict`/`from_dict`

### Kitchen "food up" path (requested by the web lane)

`tests/test_pass_api.py`: fire an order -> `order.fired` + `pass.state` to organizer sockets ->
`POST /pass/up` per line -> 409s for not-fired / bad line / already-up -> when the course is complete a
`RUN` task is created per runner and reaches the server's socket as `task.assigned` with one item per
plate; `priority` on the task is the run score.

**Runs only go to a free server** (found live by the web lane: with a dispatch after every food-up, each
course left alone the moment it was ready and hot plates never paired). Rule, in `Store.dispatch()`: a
server is free when they have no open `RUN` task; the highest-scoring run takes the section's free
server first, then anyone free; if it needs more hands than are free, the runs below it wait too (free
hands are reserved for the best run, so a 5-plate course is not starved by single plates). Everything
not dispatched stays `up` at the pass and is re-planned after every food-up, every task state change
(done, bounce, escalation) and on the 1 s ticker, so the 5-minute ceiling fires on its own.
`test_two_hot_courses_pair_because_the_runner_was_busy` is the live repro: T4 soup and T2 ribeye go
out in one trip once Ava is done with her previous run.

`POST /orders/{id}/cancel` now tells organizer sockets (`order.cancelled {order}`) and the glasses that
hold the draft (`order.closed`); confirm sends `order.closed` to the glasses too.

### Order tools

`tests/test_orders.py`: alias resolution, unknown dish -> `didYouMean` (closest names), disallowed
alteration -> `flagged`, never applied; allergy conflicts reported; confirm/cancel only propose
(`needs_confirmation` + `order.readback`), the tap (`order.confirm` on the socket or
`POST /orders/{id}/confirm`) fires. Behaviour copied from `backend/voice/order.py`, not the code.

## Measured

- Full test suite: 70 tests, ~1.1 s.
- Socket round trip (task.accept -> task.updated) in the walkthrough: < 10 ms on localhost.
- Escalation timing: 2.14 s / 4.14 s / 6.14 s after `sent` for a 2 s timeout (1 s ticker granularity).

## Surprises

- `starlette`'s test client raises `WebSocketDisconnect(code=4401)` for our bad-token close; match on
  `.code`, not the message.
- An organizer socket with no `staff` used to default to `s1` and count as delivery (reported by the web
  lane); fixed: organizer defaults to `staff=organizer` and never counts as delivery.
- `main` merged the voice spike while this branch was open; `data/menu.json` is a superset of
  `backend/voice/menu.json` (same 8 dishes + 5 more), so Coder B can switch the path without data changes.

## HW-PENDING

- The glasses app on real G2 against this server (only the simulator path is documented above).
- 3200-byte audio frames from the real mic: only counted today (`[fs] audio frames: N`), relay is B's 7b.
- WebSocket reconnect after the Even Hub background reload: the backend re-sends open tasks on connect
  (`send_current_state`), not tested from a real phone.

## Environment note

The repo blueprint's setup step had failed, so this lane installed its own toolchain: Python 3.11.15
(pyenv) venv in `backend/.venv` with `fastapi==0.115.12 uvicorn[standard]==0.34.2 websockets==15.0.1
httpx==0.28.1 pydantic==2.14.1 pytest==8.3.5 ruff==0.11.8` (`backend/requirements.txt`).
