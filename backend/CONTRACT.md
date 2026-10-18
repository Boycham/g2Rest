# Floor Sense message contract (Python-side mirror)

Status: **the source is Coder B's `glasses/src/contract.ts` on `main`** ("PROPOSED, needs Coder A
sign-off"). This file is its Python-side mirror: same message types, same camelCase field names, same
shapes. The backend signs off on it as written. `backend/app/contract.py` holds pydantic models that match
`contract.ts` exactly (`extra="forbid"`), plus a second set with the additions the backend asks for; every
inbound frame is parsed with the first set (+ the additions), every outbound frame is checked against the
second before it goes down a socket, and `tests/test_contract.py` proves the base models still parse what we
send once the extras are dropped. What the backend needs changed is listed only under
**§8 Contract changes requested**; nothing in `glasses/` is edited by this lane.

Every field name is camelCase on the wire. Times are seconds (`sinceSec`) or ISO-8601 UTC strings (`*At`).

## 1. Transport

- One WebSocket per glasses session: `ws(s)://<host>/ws?token=<FS_TOKEN>&role=server&staff=s1`
  - `token`: the shared token from the backend's `FS_TOKEN` env var. Required whenever `FS_TOKEN` is set;
    when it's empty (local dev) the backend accepts any connection. A bad token closes the socket with
    code `4401`.
  - `role`: `server` | `manager` | `organizer`. Default `server`.
  - `staff`: staff id from `floor.json` (`s1`, `s2`, `m1`). Default: the first server, so the glasses
    app on `main` (no query params) still works.
- JSON text frames `{"type": "...", ...}` in both directions, except `capture.audio`, which is a binary frame.
- HTTP calls carry the same token as `Authorization: Bearer <FS_TOKEN>` (or `?token=`). `GET /health` is open.
- On connect the backend sends **current state, not a replay**: one `task.assigned` per open task for that
  staff member (state `assigned` or `accepted`), then `floor.state`, then every open `alert`.
- Unknown message types and malformed messages are logged (`[fs]`) and ignored; the socket stays open.
- Extra fields may be added later; receivers must ignore fields they don't know.

## 2. Shared shapes

```jsonc
// Task: one card on the server's glasses.
{
  "id": "task-1a2b",
  "kind": "RUN",                 // RUN | CLEAR | CHECK | SEAT
  "table": "T12",                // table label as shown to staff
  "items": [{ "qty": 2, "dish": "halibut", "seats": [1, 3] }],
  "allergies": [{ "allergen": "SHELLFISH", "seats": [3] }],   // uppercase allergen
  "notes": ["VIP: anniversary"],
  "state": "assigned",           // assigned | accepted | done | bounced  (wire states, see §6)
  "assignee": "s1",              // PROPOSED: staff id this copy of the task belongs to
  "priority": 36.5,              // PROPOSED: run-priority score at send time (higher = sooner)
  "createdAt": "2026-10-18T02:00:00Z"   // PROPOSED
}

// OrderLine: one line of a voice-captured order, by seat.
{ "seat": 1, "qty": 1, "dish": "Pan-Roasted Halibut", "alterations": ["no capers"], "flagged": ["extra cheese"] }

// Allergy
{ "allergen": "SHELLFISH", "seats": [3] }

// TableState: one table on the floor minimap.
{ "table": "T4", "status": "waiting", "sinceSec": 840, "x": 9, "y": 0, "urgency": 3 }
// status: empty | seated | ordered | waiting | eating | check ; urgency 0 (fine) .. 4 (now)
```

## 3. Glasses -> backend

| type | fields | backend effect |
|---|---|---|
| `task.accept` | `taskId` | task `sent -> accepted`; `task.updated` echoed to the assignee; organizer sees it |
| `task.done` | `taskId` | task `accepted -> done` (also allowed straight from `sent`); next queued card is already on the glasses |
| `task.bounce` | `taskId` | task leaves this server (`task.updated` with state `bounced`) and is re-sent to the next server as a new `task.assigned` with the **same id** |
| `capture.start` | `captureId` | opens a voice capture for this staff member's current table; mic audio frames follow |
| `capture.audio` | binary frame | raw PCM 16 kHz, s16le, mono, 3200 bytes = 100 ms, belonging to the last `capture.start` on this socket |
| `capture.stop` | `captureId` | closes the capture (trailing silence is the backend's job) |
| `order.confirm` | `orderId` | fires the draft to the kitchen (the agent only proposed it) |
| `order.cancel_confirm` | `orderId` | cancels the draft (the agent only proposed it) |

```json
{ "type": "task.accept", "taskId": "task-1a2b" }
{ "type": "task.done", "taskId": "task-1a2b" }
{ "type": "task.bounce", "taskId": "task-1a2b" }
{ "type": "capture.start", "captureId": "cap-7f3e", "table": "T12" }
{ "type": "capture.stop", "captureId": "cap-7f3e" }
{ "type": "order.confirm", "orderId": "order-9c1d" }
{ "type": "order.cancel_confirm", "orderId": "order-9c1d" }
```

`capture.start.table` is PROPOSED and optional: without it the backend uses the table of the server's
current card, or the organizer can set it with `POST /captures/{captureId}/table`.

## 4. Backend -> glasses

```jsonc
// A new card for this server. Full task object.
{ "type": "task.assigned", "task": { ...Task } }

// Full replacement of a task the glasses already have (accepted, done, bounced, items changed).
{ "type": "task.updated", "task": { ...Task } }

// Live order while a capture is open. Full replacement every time a tool call lands.
{
  "type": "order.draft",
  "orderId": "order-9c1d",
  "captureId": "cap-7f3e",
  "table": "T12",
  "lines": [ { ...OrderLine } ],
  "allergies": [ { ...Allergy } ]
}

// The agent proposes sending or cancelling; only a tap on the glasses does it.
{ "type": "order.readback", "orderId": "order-9c1d", "action": "confirm", "text": "Send T12: 2x halibut, 1x risotto?" }

// Manager exception. Re-sending the same id replaces it; cleared=true removes it.
{ "type": "alert", "id": "late-T4", "level": "urgent", "text": "T4 waiting {elapsed} on mains", "table": "T4", "sinceSec": 840 }
{ "type": "alert", "id": "late-T4", "level": "urgent", "text": "", "cleared": true }
// level: info | warn | urgent

// Full snapshot of every table; sent on connect and on every change.
{ "type": "floor.state", "tables": [ { ...TableState } ] }
```

Delivery rules:
- `task.assigned` / `task.updated` go only to the task's assignee (and to organizer sockets).
- `order.*` go to the socket that opened the capture.
- `alert` and `floor.state` go to manager and organizer sockets.
- The glasses may apply taps optimistically; the backend's `task.updated` is the truth and wins.

## 5. HTTP API (shared token)

Agent tools. The voice lane's ElevenLabs agent calls these (or the voice module calls them in-process).
Each returns `200` with a JSON result **even on a rule violation** (`{"error": "..."}`), so the agent
gets the error as a tool result and the session never crashes. Only a bad token returns `401`.
All six take `table` (label, e.g. `"T12"`) and act on that table's current draft order, creating one if none
is open.

| POST | body | result |
|---|---|---|
| `/tools/add_item` | `{table, seat, dish, qty?, alterations?: []}` | `{status:"ok", orderId, line}`; unknown dish: `{error, didYouMean:[...]}`; disallowed alteration: `flagged:[...]` and a `warning`, never applied |
| `/tools/remove_item` | `{table, seat, dish}` | `{status:"ok"|"not_found", ...}` |
| `/tools/modify_item` | `{table, seat, dish, change}` | `{status:"ok", applied:[...], flagged:[...]}` |
| `/tools/set_allergy` | `{table, seat, allergen}` | `{status:"ok", allergies:[...], allergyConflicts:[...]}` |
| `/tools/confirm_order` | `{table}` | `{status:"needs_confirmation", orderId}`; sends `order.readback(action=confirm)` to the glasses |
| `/tools/cancel_order` | `{table, items?: []}` | `{status:"needs_confirmation", orderId}`; sends `order.readback(action=cancel)` |

Every tool call also pushes a fresh `order.draft` to the glasses that own the capture.

Operations (used by the organizer page, the walkthrough script and the simulator):

| method + path | purpose |
|---|---|
| `GET /health` | `{ok, tasksOpen, clients}` (no token) |
| `GET /state` | tables, orders, tasks, open alerts |
| `GET /events?since=<n>` | append-only event log (`seq`, `at`, `type`, `data`) |
| `GET /menu`, `GET /floor` | the loaded `data/menu.json`, `data/floor.json` |
| `POST /tasks` | create a task: `{kind, table, items?, allergies?, notes?, assignee?}`; without `assignee` the table's section server gets it |
| `POST /tasks/{id}/{accept|done|bounce}` | same as the glasses gestures, for the organizer |
| `POST /tables/{id}/status` | `{status}`; broadcasts `floor.state` |
| `POST /plates` | `{table, dish, seat?, orderId?}` registers a plate the kitchen is cooking |
| `POST /plates/{id}/up` | the plate is at the pass; the priority engine re-plans runs |
| `GET /runs?mode=priority|fifo` | the planned runs (debug view of the engine) |
| `POST /reset` | clears orders, tasks, plates and alerts (keeps menu and floor) |

### 5.1 Pass (kitchen page; not part of the glasses contract)

- `GET /pass` -> `{planner, plates: [{plateId, orderId, line, table, seat, dish, course, temperature,
  upSec, score, status: "waiting"|"up"|"running"}], holds: [{table, course, waitingOn: [dish]}],
  runs: [{runId, tables, section, runners, assignees, score, hot, reason, plates}]}`.
  `plateId` is `"<orderId>:<line>"`; one plate per order line even when `qty > 1`.
- `POST /pass/up {orderId, line}` -> same body. 409 if the order is not fired, the line is bad or the
  plate is already up. A run leaves only when a server with no open `RUN` task is free (highest score
  first; the section's server first, then anyone free); otherwise the plates wait `up` at the pass and
  are re-planned on every task change and on the ticker.
- `POST /pass/planner {"planner": "priority"|"fifo"}` (simulator switch).
- Organizer sockets only (`role=organizer`): `{"type": "pass.state", ...GET /pass body}` after every
  change, `{"type": "order.fired", "order"}` when an order fires, `{"type": "order.cancelled", "order"}`
  when a draft is cancelled. Glasses never receive these.

## 6. Task lifecycle (backend)

```
queued -> sent -> accepted -> done
  |        |
  |        +--(task.bounce)-----------------> bounced  -> re-queued for the next server (same id)
  |        +--(30 s after sent, no accept)--> escalated -> re-queued for the next server, then the manager
  +--(assignee's socket is up)--> sent
```

Backend state -> what the glasses see (`Task.state` in `contract.ts`):

| backend (`backendState` on HTTP) | wire `state` | message |
|---|---|---|
| `queued` | (nothing yet) | the card is waiting for the assignee's socket |
| `sent` | `assigned` | `task.assigned` |
| `accepted` | `accepted` | `task.updated` |
| `done` | `done` | `task.updated` |
| `bounced`, `escalated` | `bounced` | `task.updated` to the previous assignee; `task.assigned` to the next |

- `queued`: assigned to a staff member whose socket isn't connected yet. Becomes `sent` the moment the
  `task.assigned` frame goes down that person's socket (organizer sockets don't count).
- **The 30 s escalation timer starts at `sent` and stops at `accepted`.** A `queued` task is not timed
  (nobody has seen it); see §8.6 for the open question that follows from that.
- Escalation order: the other servers of the task's section, then any other server, then the manager
  (`m1`). The manager is the end of the chain: after that an `alert` (`task unacknowledged`) is raised instead.
- `bounced` and `escalated` are what the previous assignee sees (`task.updated`, state `bounced`); the glasses
  drop the card. The new assignee gets `task.assigned` with the same `id`.
- Every transition is appended to the event log with `taskId`, `from`, `to`, `assignee`, `reason`.
- Timeout is `FS_ESCALATION_SEC` (default 30); the walkthrough script lowers it.

## 7. Data files

### `data/menu.json`

Identical to `backend/voice/menu.json` on `origin/devin/voice-spike` so both lanes read one file.

```jsonc
{
  "restaurant": "string",
  "dishes": [
    {
      "name": "Pan-Roasted Halibut",        // unique, shown on cards
      "aliases": ["halibut"],               // what people say; matched case/hyphen-insensitively
      "course": "main",                     // appetizer | main | dessert
      "temperature": "hot",                 // hot | warm | room | cold
      "allergens": ["fish", "dairy"],       // lowercase
      "allowed_alterations": ["no butter"]  // anything else is flagged, never applied
    }
  ]
}
```

### `data/floor.json`

```jsonc
{
  "restaurant": "string",
  "sections": [{ "id": "A", "name": "Window", "server": "s1" }],
  "servers":  [{ "id": "s1", "name": "Ava", "sections": ["A"] }],
  "manager":  { "id": "m1", "name": "Dana" },
  "tables":   [{ "id": "T1", "section": "A", "seats": 2, "x": 0, "y": 0 }]  // x right, y down, any unit
}
```

`tables[].x/y` feed `TableState.x/y`; `section` picks the default assignee for a table's tasks.

## 8. Contract changes requested (for Coder B; nothing here is applied to `glasses/`)

Each item is modelled in `backend/app/contract.py` §2 as an `*Ext` class. All are additive: `parse.ts`
ignores unknown keys today, so the current glasses build keeps working whether or not they are accepted.

1. **Connection query params** `?token=&role=&staff=` on the WebSocket URL. `role` is `server`
   (default) | `manager` | `organizer`; `staff` is a `floor.json` id (defaults: first server, `m1`,
   `organizer`). The token ships in the bundle either way (see
   `.agents/skills/g2-glasses-integration/04-ARCHITECTURE.md`); `VITE_BACKEND_URL` can carry it:
   `ws://host:8787/ws?token=...&role=server&staff=s1`.
2. **`Task` + `assignee: string`, `priority: number`, `createdAt: string`** (ISO-8601 UTC). The glasses
   may ignore all three; the organizer and kitchen pages use them.
3. **`TableState` + `x`, `y`, `urgency`** and **`Alert` + `table?`, `sinceSec?`, `cleared?`** exactly as
   proposed on `origin/devin/manager-hud`. The backend already sends them.
4. **New backend -> glasses message `order.closed`** `{type, orderId, status: "fired" | "cancelled"}`:
   the answer to `order.confirm` / `order.cancel_confirm`, so the glasses can drop the draft screen.
5. **`capture.start` + `table?: string`**: if the glasses know the table of the current card when the
   server swipes down, send it; otherwise the backend uses the table of the server's current card.
6. **Open question, not a field:** should a task that is `queued` for an offline server (never `sent`)
   also escalate after 30 s? Today it waits for the socket; the backend lane thinks it should escalate
   too, which would need no contract change, only agreement.
7. **Confirmation of semantics already in `contract.ts`:** (a) a bounce shows the previous assignee
   `task.updated` with `bounced` and the next one `task.assigned` with the same `id`; (b) `task.done`
   straight from `assigned` (no accept) is allowed so a fast double tap never leaves a stuck task;
   (c) order-tool HTTP results are camelCase (`didYouMean`, `allergyConflicts`, `flagged`) like the wire,
   while `backend/voice/order.py` is snake_case internally; pick one before the agent prompt is final.
