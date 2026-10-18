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

- One WebSocket per tab: `/ws?role=organizer&staff=organizer`. `staff=organizer` matters: without
  it the hub defaults the socket to server `s1`, pushes s1's tasks to the tab and marks them sent.
  Reported to the backend-core session.
- `GET /state` on every (re)connect, then live messages through the reducer in `state.js`.
- The kitchen also resyncs `GET /state` 150 ms after `floor.state` or `order.closed`, because
  firing an order from `POST /orders/{id}/confirm` only pushes `floor.state`.
- Every call has a 4 s timeout; failures show as a red toast, the socket pill shows
  "reconnecting…".

## Measured (headless Chrome 155 via playwright-core 1.55, local backend, Oct 17)

| Path | Time |
|---|---|
| Dispatch in tab A -> row in tab B | 43 ms (197 ms cold first run) |
| Accept in tab B -> accepted in tab A | 46 ms |
| Fire order -> ticket on kitchen rail | 185-203 ms (includes the 150 ms resync debounce) |
| Food up -> RUN on organizer board | 54-58 ms |

## Direct mode (temporary)

The kitchen's "Food up" posts to `POST /pass/up {orderId, line}`, which belongs to the priority
engine (step 4, backend-core session). Until the backend has `GET /pass`, the kitchen shows
**DIRECT MODE** and food up creates a RUN task for the table's section server with no scoring
or pairing. The "up" marks are kept in the tab only and are lost on reload. Delete the direct
path once `/pass` lands.

Requested from the backend lane (in the backend-core Devin session):

- `POST /pass/up`, `GET /pass` (plates with `line`, `score`, `upSec`, `status`; `holds` with
  `waitingOn`), and a `pass.state` broadcast to organizer sockets.
- `order.fired` broadcast to organizer sockets, so the kitchen doesn't need the resync.
- Organizer sockets default to staff `organizer`, never a server.

## Not done yet

- Floor-plan editor (drag tables, assign sections). The plan lists it; the backend has no
  route to save a floor yet.
- Task templates (drinks, VIP touch): the contract's task kinds are RUN, CLEAR, CHECK, SEAT,
  so the organizer sends one of those with a note.
- Phone layout is usable but not tuned; the organizer on the phone is the Even Hub app's job.
