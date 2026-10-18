# Web pages: notes

Organizer (`index.html`) and kitchen (`kitchen.html`) pages for step 5 of the build plan. Plain
HTML, CSS and ES modules: no framework, no build step, no npm dependencies.

## Run it

```sh
# backend (repo root .env is read; empty FS_TOKEN = open dev mode)
cd backend && FS_TOKEN= .venv/bin/uvicorn app.main:app --port 8787

# pages
cd web && python3 -m http.server 5173
open http://localhost:5173/index.html      # organizer
open http://localhost:5173/kitchen.html    # kitchen
```

Point the pages at another backend with `?api=https://host&token=...`, for example
`index.html?api=https://floor.example.com&token=dev`.

Tests: `cd web && node --test` (Node 24, built-in runner; covers `state.js`).

## How it talks to the backend

- One WebSocket per tab: `/ws?role=organizer&staff=organizer`. The hub now defaults organizer
  sockets to staff `organizer` too; the pages still pass it explicitly.
- `GET /state` on every (re)connect (it includes the pass), then live messages through the
  reducer in `state.js`: `task.*`, `floor.state`, `alert`, `order.draft`, `order.closed`, and
  the web-only `order.fired` and `pass.state`.
- Food up is `POST /pass/up {orderId, line}`. The backend's planner decides every run; the page
  only shows what it decided.
- Every call has a 4 s timeout; failures show as a red toast, the socket pill shows
  "reconnecting…".

## The kitchen's pass panel

- Each ticket line follows its plate: `Food up` (waiting), `Up`, `Running`.
- "Held" lists only courses where some plates are up and others are not, naming the dishes it
  waits on. A course with nothing up yet is still cooking, so it isn't listed.
- "Runs" lists the open RUN tasks with who has them and the engine's reason.

## Measured (headless Chrome 155 via playwright-core 1.55, local backend, Oct 17)

| Path | Time |
|---|---|
| Dispatch in tab A -> row in tab B | 43-92 ms (197 ms cold first run) |
| Accept in tab B -> accepted in tab A | 18-47 ms |
| Fire order -> ticket on kitchen rail | 14-15 ms (185-203 ms before `order.fired`, with a resync) |
| Second main up -> one run with both mains on the organizer board | 19-33 ms |
| First main up -> RUN tasks created while the course is held | 0 (correct) |

## Surprise: hot plates never pair up live

`POST /pass/up` runs the planner after every plate, so a course leaves the moment it is ready.
Two hot courses from one section only pair if they become ready in the same call, which a
person pressing buttons never does. Check run (T4 and T2 are both in section A):

```
run-1: T4 mains x2          <- both mains, correctly held then sent together
run-2: T4 appetizers x1     <- hot soup, sent alone
run-3: T2 mains x1          <- hot ribeye up a moment later, sent alone to the same server
```

The pairing rule is right and unit-tested in `backend/tests/test_runs.py`; it is the dispatch
timing that never gives it two ready courses. Raised with the backend lane, not fixed here.

## Not done yet

- Floor-plan editor (drag tables, assign sections). The plan lists it; the backend has no
  route to save a floor yet.
- Task templates (drinks, VIP touch): the contract's task kinds are RUN, CLEAR, CHECK, SEAT,
  so the organizer sends one of those with a note.
- Cancelling a draft with `POST /orders/{id}/cancel` notifies no one, so the kitchen keeps
  showing it under "Taking order" until the next reconnect. Cancels from the glasses send
  `order.closed` and are fine.
- Phone layout is usable but not tuned; the organizer on the phone is the Even Hub app's job.
