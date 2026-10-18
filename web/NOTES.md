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
  the web-only `order.fired`, `order.cancelled` and `pass.state`.
- Food up is `POST /pass/up {orderId, line}`. The backend's planner decides every run; the page
  only shows what it decided.
- The board only watches tasks. Accept, done and bounce come from the assignee's glasses (or
  `POST /tasks/{id}/{action}?by=<assignee>` in tests); the organizer can't close a server's task.
- Every call has a 4 s timeout; failures show as a red toast, the socket pill shows
  "reconnecting…".

## The kitchen's pass panel

- Each ticket line follows its plate: `Food up` (waiting), `Up`, `Running`.
- "Held" lists only courses where some plates are up and others are not, naming the dishes it
  waits on. A course with nothing up yet is still cooking, so it isn't listed.
- Each plate that is up reads "held" (its course isn't complete) or "needs a server" (the
  course is ready and every server already has a run out).
- "Runs" lists the open RUN tasks with who has them and the engine's reason.

## Measured (headless Chrome 155 via playwright-core 1.55, local backend, Oct 17)

| Path | Time |
|---|---|
| Dispatch in tab A -> row in tab B | 43-92 ms (197 ms cold first run) |
| Accept in tab B -> accepted in tab A | 18-47 ms |
| Fire order -> ticket on kitchen rail | 14-20 ms (185-203 ms before `order.fired`, with a resync) |
| Second main up -> one run with both mains on the organizer board | 19-59 ms |
| First main up -> RUN tasks created while the course is held | 0 (correct) |
| Both servers out, two hot courses up -> RUN tasks created | 0 (correct: they wait) |
| Ava taps done -> paired run (T4 soup + T2 ribeye) on the board | 39-41 ms |
| Cancel a draft -> gone from the kitchen | 3-5 ms |

## Hot pairing: fixed in the backend, checked here

The first version of the pass ran the planner after every plate, so a course left the moment it
was ready and two hot courses never met. The backend now hands a run only to a server with no
open RUN task (eb97a29). The kitchen check reproduces the pairing with both servers busy:

```
run-1 -> s1: T4 mains x2                       <- held, then sent together
run-2 -> s2: T6 mains x1                       <- keeps Ben busy
run-3 -> s1: T4 appetizers x1, + T2 hot x1     <- waited at the pass, left together when Ava finished
```

Open question from the backend lane: free servers are reserved for the top run, so a course
that needs two runners can briefly hold back smaller runs when only one server is free.

## Not done yet

- Floor-plan editor (drag tables, assign sections). The plan lists it; the backend has no
  route to save a floor yet.
- Task templates (drinks, VIP touch): the contract's task kinds are RUN, CLEAR, CHECK, SEAT,
  so the organizer sends one of those with a note.
- Phone layout is usable but not tuned; the organizer on the phone is the Even Hub app's job.
