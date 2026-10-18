# Floor Sense message contract (PROPOSAL)

Status: **proposed by the backend lane (Coder A), needs Coder B's approval.** It is written to match
`glasses/src/contract.ts` on `main` plus the manager-HUD additions on `origin/devin/manager-hud`
(`TableState.x/y/urgency`, `Alert.table/sinceSec/cleared`), so nothing the glasses already send or parse
changes. Differences and open questions are listed at the end. Once both lanes agree, this file is frozen
and any change goes through a PR that touches both lanes' docs.

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

## 6. Task lifecycle (backend)

```
queued -> sent -> accepted -> done
  |        |
  |        +--(task.bounce)-----------------> bounced  -> re-queued for the next server (same id)
  |        +--(30 s without accept)---------> escalated -> re-queued for the next server, then the manager
  +--(server connects)--> sent
```

- `queued`: assigned to a staff member whose socket isn't connected yet. Becomes `sent` the moment it goes
  down a socket.
- `sent` is shown to the glasses as `assigned` (the glasses never see `queued`).
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

## 8. Differences from `glasses/src/contract.ts` and open questions for Coder B

1. **Connection query params** (`token`, `role`, `staff`): new. Defaults keep the current glasses app
   working, but the real build should send them (and `VITE_BACKEND_URL` should include `?token=`,
   or the token can be a separate `VITE_BACKEND_TOKEN`; it ships in the bundle either way, see
   `.agents/skills/g2-glasses-integration/04-ARCHITECTURE.md`).
2. **Task extra fields** `assignee`, `priority`, `createdAt`: additive; `parse.ts` already ignores extras.
3. **Bounce semantics**: the glasses get `task.updated` with `bounced` (already handled: the card is
   dropped), and the next server gets `task.assigned` with the same id. OK?
4. **`capture.start.table`** (optional): is the table known on the glasses when the server swipes down?
   If not, the backend falls back to the table of the current card.
5. **`task.done` from `sent`** (no accept first) is accepted by the backend so a fast double-tap never
   leaves a stuck task. OK?
6. **Order tool results are camelCase** (`didYouMean`, `allergyConflicts`, `flagged`) to match the wire;
   `backend/voice/order.py` uses snake_case internally. Pick one before the agent prompt is finalised.
7. **Who hosts the tools**: the backend exposes `/tools/*` over HTTP; the voice module can call them with
   `httpx` or import `backend/app/orders.py` directly. Either way the rule guards live in one place.
