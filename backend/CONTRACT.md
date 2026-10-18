# Floor Sense message contract (Python-side mirror)

Status: **signed off by both lanes at Sync 1.** The source is `glasses/src/contract.ts`; this file is its
prose, and `backend/app/contract.py` holds pydantic models that match it (`extra="forbid"`), plus a second
set with the backend's additions (§8). Every inbound frame is parsed with the extended set, every outbound
frame is checked against it before it goes down a socket, and `tests/test_contract.py` proves the base
models still parse what we send once the extras are dropped.

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
  "kind": "RUN",                 // RUN | CLEAR | CHECK | SEAT | ORDER
  "table": "T12",                // table label as shown to staff
  "items": [{ "qty": 2, "dish": "halibut", "seats": [1, 3] }],
  "allergies": [{ "allergen": "SHELLFISH", "seats": [3] }],   // uppercase allergen
  "notes": ["VIP: anniversary"],
  "state": "assigned",           // assigned | accepted | done | bounced  (wire states, see §6)
  "assignee": "s1",              // staff id this copy of the task belongs to
  "priority": 36.5,              // run-priority score at send time (higher = sooner)
  "createdAt": "2026-10-18T02:00:00Z"
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
| `capture.start` | `captureId`, `table?`, `mode?` | opens a voice capture; the table is `table`, else the server's open ORDER task, else none (spoken later). `mode: "clip"`: the frames that follow are the last minute from the glasses' rolling buffer |
| `task.handoff` | `taskId`, `to?` | gives an open task (accepted or not) to `to` (a staff id or name, any case: `"Ben"`); without `to` the router (Gemini, else rules) picks anyone but the sender. Same frames as a bounce: `bounced` to the sender, `task.assigned` (same `id`) to the new holder |
| `task.revert` | `taskId?` | undoes the sender's **last** accept, done, bounce or handoff (one level): un-accept -> `task.updated` `assigned` with a fresh 30 s timer; un-done -> `task.assigned` (the card comes back, state as before); un-bounce/un-handoff -> the task comes back with `task.assigned`, the holder gets `bounced`, but only while the holder hasn't accepted it |
| `capture.audio` | binary frame | raw PCM 16 kHz, s16le, mono, 3200 bytes = 100 ms, belonging to the last `capture.start` on this socket |
| `capture.stop` | `captureId` | closes the capture (trailing silence is the backend's job) |
| `order.confirm` | `orderId`, `proposalId?` | without `proposalId`: fires the draft to the kitchen (the agent only proposed it); with it: applies that pending voice proposal |
| `order.cancel_confirm` | `orderId`, `proposalId?` | without `proposalId`: cancels the draft (the agent only proposed it); with it: applies that pending cancel proposal |
| `order.reject` | `orderId`, `proposalId` | swipe up on a pending voice proposal: drops it, nothing changes |

```json
{ "type": "task.accept", "taskId": "task-1a2b" }
{ "type": "task.done", "taskId": "task-1a2b" }
{ "type": "task.bounce", "taskId": "task-1a2b" }
{ "type": "capture.start", "captureId": "cap-7f3e", "table": "T12" }
{ "type": "capture.stop", "captureId": "cap-7f3e" }
{ "type": "order.confirm", "orderId": "order-9c1d" }
{ "type": "order.cancel_confirm", "orderId": "order-9c1d" }
{ "type": "order.confirm", "orderId": "3f9a1c2e", "proposalId": "p2" }
{ "type": "order.reject", "orderId": "3f9a1c2e", "proposalId": "p3" }
```

Voice orders (Sync 1): `capture.*` and the `order.*` taps for a relay order (one whose `orderId` came from a
relay `order.draft`) are forwarded by `app/voice_bridge.py` to `backend/voice/relay.py`; the final tap fires
the relay's lines into this backend's order store (§5 tools), then `order.closed` comes back as usual.

`capture.start.table` is optional: without it the backend uses the table of the server's
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
  "allergies": [ { ...Allergy } ],
  // optional, sent by the voice relay:
  "status": "draft",                // draft | sent | cancelled; sent/cancelled only after the tap
  "pending": [ { "id": "p2", "action": "remove", "text": "REMOVE s2 soup?" } ], // remove | cancel | confirm
  "voice": "listening",             // idle | connecting | listening | offline (VOICE OFFLINE)
  "notice": null                    // one line: why the last tool call was refused
}

// The answer to the send / cancel tap: the glasses leave the draft screen.
{ "type": "order.closed", "orderId": "order-9c1d", "status": "fired" }   // fired | cancelled

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

```jsonc
// A task.* frame from this socket was refused (wrong owner, unknown name, nothing to revert,
// "Ben already accepted it"). Only to the sending socket; `reason` is short enough for the card.
{ "type": "task.rejected", "taskId": "task-4f2a" | null, "action": "accept" | "done" | "bounce" | "handoff" | "revert", "reason": "Ben already accepted it" }
```

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
| `GET /stats` | how long each server takes: `{doneSec, servers: [{id, name, done, avgSec, avgSecByKind: {CHECK: 60}, open: [{taskId, kind, table, state, heldSec}]}]}`; `avgSec` is accept to done over this service's finished tasks (`null` before the first), `heldSec` counts from accept (or from assignment if not accepted yet) |
| `GET /events?since=<n>` | append-only event log (`seq`, `at`, `type`, `data`) |
| `GET /menu`, `GET /floor` | the loaded `data/menu.json`, `data/floor.json` |
| `POST /tasks` | create a task: `{kind, table, items?, allergies?, notes?, assignee?}`; without `assignee` Gemini picks the server (`app/router.py`), falling back to the table's section server |
| `POST /tasks/{id}/{accept|done|bounce}?by={staff}` | same as the glasses gestures, for the simulator and tests; `by` must be the assignee (409 otherwise), so only the server holding a task closes it, never the organizer |
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
  +--(2 min queued, socket never up)------> escalated -> re-queued for the next server, then the manager
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
- **The 30 s escalation timer starts at `sent` and stops at `accepted`.** A `queued` task (its server's
  socket is offline, nobody has seen it) escalates after `FS_OFFLINE_ESCALATION_SEC` (default 120) from
  when it was assigned (§8.6).
- Escalation order: the other servers of the task's section, then any other server, then the manager
  (`m1`). The manager is the end of the chain: after that an `alert` (`task unacknowledged`) is raised instead.
- `bounced` and `escalated` are what the previous assignee sees (`task.updated`, state `bounced`); the glasses
  drop the card. The new assignee gets `task.assigned` with the same `id`.
- Every transition is appended to the event log with `taskId`, `from`, `to`, `assignee`, `reason`.
- Timeout is `FS_ESCALATION_SEC` (default 30); the walkthrough script lowers it.
- **Done timer: an accepted task not done after `FS_DONE_SEC` (default 300) raises a `warn` alert**
  to the manager (`id: "slow-<taskId>"`, text like `T4 check: Ava 5:00, moved to Ben`) and the router
  moves it to someone else (`escalated`, same frames as a bounce; the new holder's timers start over).
  A `RUN` is only flagged, never moved: its plates are in the server's hands. Done clears the alert.

## 7. Data files

### `data/menu.json`

The one menu: the backend and `backend/voice` (order guards, agent prompt) both read this file.

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

## 8. Contract changes (signed off at Sync 1)

All of these are now in `glasses/src/contract.ts` (no `PROPOSED` markers left) and modelled in
`backend/app/contract.py`. They are additive: `parse.ts` ignores unknown keys.

1. **Connection query params** `?token=&role=&staff=` on the WebSocket URL. `role` is `server`
   (default) | `manager` | `organizer`; `staff` is a `floor.json` id (defaults: first server, `m1`,
   `organizer`). The glasses build the query from `VITE_BACKEND_URL`, `VITE_FS_TOKEN` and the role picker
   (`glasses/NOTES.md`). The token ships in the bundle (dev token only; see
   `.agents/skills/g2-glasses-integration/04-ARCHITECTURE.md`).
2. **`Task` + `assignee: string`, `priority: number`, `createdAt: string`** (ISO-8601 UTC). Always sent;
   optional in `contract.ts` because the glasses ignore all three; the organizer and kitchen pages use them.
3. **`TableState` + `x`, `y`, `urgency`** and **`Alert` + `table?`, `sinceSec?`, `cleared?`**, as on
   `origin/devin/manager-hud`.
4. **Backend -> glasses `order.closed`** `{type, orderId, status: "fired" | "cancelled"}`: the answer to
   `order.confirm` / `order.cancel_confirm`; the glasses leave the draft screen and go back to the card.
5. **`capture.start` + `table?: string`**: if the glasses know the table of the current card, they may send
   it; otherwise the backend uses the table of the server's current card.
6. **Decided (owner):** a task `queued` for an offline server (never `sent`) escalates after **2 minutes**
   (`FS_OFFLINE_ESCALATION_SEC`, default 120), down the same chain as the 30 s timer.
7. **Decided (owner):** (a) a bounced task goes to the **next server in the chain**: the previous
   assignee sees `task.updated` with `bounced`, the next one `task.assigned` with the same `id`;
   (b) **`task.done` straight from `assigned`** (no accept) is allowed, so a fast double tap never leaves
   a stuck task; (c) order-tool HTTP results stay camelCase (`didYouMean`, `allergyConflicts`, `flagged`)
   like the wire; `backend/voice/order.py` keeps snake_case internally behind the relay.
8. **Voice fields** from the voice capture lane: `order.confirm` / `order.cancel_confirm` + `proposalId?`,
   `order.reject {orderId, proposalId}`, and `order.draft` + `status?`, `pending?`, `voice?`, `notice?`.
9. **Conversational capture (proposed by the glasses lane, branch `devin/conversational-capture`):**
   - `TaskKind` + `ORDER`: "take T3's order". Accepting it on the glasses binds the next clip to that
     table; the backend also uses the server's open ORDER task as the capture's table when
     `capture.start` has none. The order firing (or being cancelled) marks the ORDER task done.
   - `capture.start` + `mode?: "stream" | "clip"`. A clip is up to 120 s of 3200-byte frames sent as
     fast as possible, then `capture.stop`; the relay transcribes it in one batch and extracts the order.
   - `VoiceState` + `processing` (the clip is being transcribed and read), and `order.draft` +
     `notes?: string[]` (occasion, pacing) and `uncertain?: string[]` (`? s2 'the fish': halibut or salmon`).
   - **Clip summary and answers (branch `devin/clip-summary`):** `order.draft` + `summary?: string`
     (1-2 lines: what the table said, mood, pacing, occasion) and
     `answers?: {seat?: number, q: string, a: string, known?: boolean}[]` (a suggested reply per guest
     question or comment, e.g. `{seat: 2, q: "risotto nuts?", a: "no tree nuts listed for risotto"}`).
     Code writes every food answer from `data/menu.json`; `known: false` means the menu can't answer it
     (`a` is `not in menu data`, shown as a `?` line). Both are display only: they are never part of the
     `Order`, never fired to the kitchen, and a clip with no dishes still carries them.
   - Organizer sockets get `{"type": "order.draft", ...Order}` (the `GET /state` order shape) while a voice
     draft builds, so the kitchen sees it forming before the fire.
10. **Handoff and revert** (Coder A, for voice "handoff" / "revert" and the long-hold handoff):
    glasses -> backend `task.handoff {taskId, to?}` and `task.revert {taskId?}`; backend -> glasses
    `task.rejected {taskId, action, reason}`. Additive; `contract.ts` needs the three types.
11. **Table by voice and the 2-minute clip (glasses lane, branch `devin/clip-summary`):**
    - A clip is now the last **120 s** (was 60 s): at most 1200 frames, 3.84 MB; the relay drops frames past
      1220.
    - Relay -> glasses `voice.command` + `intent: "table"` with `table?: string` (`"T4"`), `was?: string`
      (the table it replaced, e.g. an ORDER task's `"T3"`) and `reason?: string` (refused: `"no table 12"`
      (not in `data/floor.json`), `"already sent"`, `"no order to set the table for"`). On success the relay
      also sends the rebound `order.draft`. "verity table N" overrides the ORDER task's table; a table said
      inside a clip ("that was table four", even as the last words) binds only when no task or
      "verity table" has set one. Only an unsent draft changes. Additive; `contract.py` `VoiceCommand`
      has the three optional fields.
