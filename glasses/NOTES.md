# glasses/ notes (server HUD, manager HUD)

## How to run

```sh
cd glasses && npm install
npx tsx dev/fake-backend.ts          # FAKE backend: ws://localhost:8787/ws, state page http://localhost:8787/
npx vite                             # app on http://localhost:5173
npx evenhub-simulator http://localhost:5173 --automation-port 9898   # restart after every app/backend restart
npm test && npm run build
```

The fake backend's page at `http://localhost:8787/` (JSON at `/state`) stands in for the organizer page: each
task's state plus every message the glasses sent. `POST /reset` clears it and replays the script on the next
connect.

The fake backend also runs a manager loop (60 s) from the first connect: 8 tables on a 4×2 floor plan,
`vip-t7` at 0 s, `unacked-t3` at 4 s, T4 goes late (urgency 4 + `late-t4` urgent alert) at 8 s, then
`unacked-t3` clears at 20 s, `vip-t7` at 30 s, `late-t4` at 40 s. `POST /late?table=T2` makes any table late
on demand. Pick the role on the phone page (Server / Manager select).

On a fresh Ubuntu 22.04 VM the simulator binary needs `sudo apt-get install libwebkit2gtk-4.1-0`, and
`npx evenhub-simulator` resolves to the npm registry instead of the local package; run
`node node_modules/@evenrealities/evenhub-simulator/bin/index.js http://localhost:5173 --automation-port 9898`.

## Confirmed versions

- `@evenrealities/even_hub_sdk` 0.0.16 (pinned exactly), `@evenrealities/pretext` 0.1.4,
  `@evenrealities/evenhub-simulator` 0.9.5, `@evenrealities/evenhub-cli` 0.1.14. Read from the installed packages.

## Checked in the simulator (0.9.5, automation port, against the fake backend)

All on 2026-10-18, driven with `POST /api/input` and read back with `/api/screenshot/glasses`, `/api/console` and
the fake backend's `/state`.

- Card appears; allergy line first (`! SHELLFISH s3`), then `RUN · T12 · 2× halibut s1+3`; corner counter
  goes `+1 queued` -> `+2 queued` as the script arrives. Updates are `textContainerUpgrade` only.
- Tap -> `task.accept` received; state page shows `accepted`; card shows `ACCEPTED` and dims.
- Tap again -> `task.done`; state page shows `done`; next card (T4, VIP note) appears with `+1 queued`.
- Swipe up -> queue screen; swipe up again -> back to the card. Swipe up, then tap -> back to the card.
- Swipe down -> `capture.start` sent, `Listening… (swipe down to stop)` shown; swipe down -> `capture.stop`
  sent (same `captureId`), card back.
- Killing the backend: card footer shows `OFFLINE` within a second, retries back off 0.5 s -> 10 s; restarting
  the backend reconnects on its own.
- Reloading the WebView (Vite reload): `restored queue 3` from SDK storage, card redrawn before the socket opens.
- Double tap -> `shutDownPageContainer(1)`; glasses go blank.
- Timings (simulator, not hardware): `textContainerUpgrade` 1-2 ms, `rebuildPageContainer` 0-3 ms per call.

Unit tests: 27 vitest tests (card formatter, queue screen, task state machine, message parser).

## Manager HUD, checked in the simulator (0.9.5, automation port, against the fake backend)

All on 2026-10-18, same tooling as above.

- Role picker: switching the phone select to Manager logs `role -> manager`, writes `fs.role.v1` with
  `setLocalStorage` and rebuilds the glasses page once. Server stays the default on a fresh install.
- Server role unchanged after the refactor: same card, `+2 queued`, tap -> `task.accept`, tap -> `task.done`
  (next card), swipe up -> queue and back, swipe down -> `capture.start` / `capture.stop`.
- Exceptions: blank at the start of each loop; `VIP seated T7`, then `T3 task unacked 40s`, then
  `! T4 waiting 14m on mains` on top, each as one `textContainerUpgrade` (1-2 ms). With no new message the
  local timer ticked `T3 task unacked 40s -> 50s -> 60s`. Clears drop lines in place; after the last clear
  the screen is blank.
- Tap on exceptions -> `dismissed locally late-t4` (no message: the contract has no ack). The next alert
  moves up.
- Swipe down -> minimap: one `rebuildPageContainer` with 8 bordered text containers (3 ms). After that,
  table changes are per-box `textContainerUpgrade` only (`box 3 upgrade "T3 W\n0m"`, 2-4 ms), no rebuild.
- Late table: `POST /late?table=T2` while on the minimap -> the next `floor.state` upgrades box 2 to
  `T2 !` at brightness 4 in one update (2 ms). Same for T5.
- Swipe up -> exceptions again; double tap -> `shutDownPageContainer(1)`, glasses blank.

Unit tests: 55 vitest tests (27 server + exceptions ordering/formatting, minimap layout/brightness, parser
checks for `alert` and `floor.state`).

### Why text containers for the minimap

The SDK has text, list and image containers. A list container swallows swipe up (see Surprises), and an
image container needs a raw Gray4 bitmap pushed with a separate `updateImageRawData` per change. A text
container has a border, padding and a per-container brightness (`textColor` 0..4) that
`textContainerUpgrade` can change in place, and a page holds up to 8 of them: exactly one per table. Only
the first box captures input.

## Surprises

- **The simulator draws brightness as alpha, not as a darker green.** Every pixel is `(0,255,0,a)`: text level
  4 has alpha 255, level 1 has 179, a level-2 border 131. On a white background (the PNG viewer default) all
  levels look the same; composite the screenshot onto black to see the lit box. Real lens: HW-PENDING.
- Border width and border colour can't be changed with `textContainerUpgrade` (only content and
  `textColor`), so urgency rides on text brightness and the `!` glyph; borders stay at level 2.
- With 8 containers on a page and only box 1 capturing input, swipes and taps still reach the app wherever
  the "finger" is, because G2 input is not positional.
- After `shutDownPageContainer(1)` the simulator blanks the glasses and later `textContainerUpgrade` calls
  return `false`. We keep rendering anyway: on hardware mode 1 shows an exit dialog the wearer can cancel.
- Manager `alert` messages say nothing about time, so `T4 waiting 14m` would freeze without a new message.
  The proposed `sinceSec` + `{elapsed}` token lets the glasses tick the number locally.
- **A list container swallows swipe up.** With the queue as a `ListContainerProperty`, swipe up only moved
  the selection; no `SCROLL_TOP_EVENT` reached the app, so "swipe up again to return" never fired (tap still
  did). The queue is now plain text in one text container (`> ` marks the current task, `+N more` after 5
  lines), so every gesture reaches the app.
- A list tap arrives as a `listEvent` with no `eventType` (CLICK_EVENT is 0 and gets dropped from the JSON),
  same as text-container taps. `eventTypeOf` defaults a missing type to CLICK.
- After a WebView reload `createStartUpPageContainer` returns `1`, not `0` (the simulator still holds the
  page from the last load); `textContainerUpgrade` keeps working. We still call it exactly once per load.
- Simulator SDK storage lives in memory: it survives a WebView reload but not a simulator restart.
- The fake backend replays its script to every new connection, so after a backend restart a task the glasses
  already finished comes back. The real backend should send current state, not a replay (see contract notes).
- `npm audit` flags transitive dev dependencies (esbuild via vite 5, vitest 1). Dev-only; not fixed with
  `--force` because that bumps majors.

## Not done here

- **No mic audio.** `capture.audio` (binary PCM frame) is in the contract and `BackendSocket.sendAudio` exists,
  but the mic is not opened and no frames are forwarded. That is the voice session's work.
- `order.draft`, `order.readback` are parsed but not drawn; `order.confirm` /
  `order.cancel_confirm` and `task.bounce` are typed but no gesture sends them yet.
- **Manager tap only dismisses locally.** The contract has no alert acknowledgement, so the dismissed alert
  stays open on the backend and comes back if the backend re-sends it. Proposed `alert.ack` in the PR.
- No Organizer role on the phone yet (AGENTS.md lists one); the select has Server and Manager only.
- The minimap draws at most 8 tables (one text container each); more are dropped after natural sort.
- `app.json` whitelists only `ws://localhost:8787` and `http://localhost:8787`. Add the real `wss://`/`https://`
  host before packing for the phone.

## HW-PENDING (real G2 + phone)

- Tap / swipe up / swipe down / double tap from both the ring and the temple; swipe up on the queue returns.
- Card legibility at each brightness; the dim `ACCEPTED` state is readable; 5-line cap fits the real lens.
- `+N queued` stays flush right on hardware (padding built from pretext widths of spaces).
- WebSocket to the real backend host from the phone WebView (whitelist + CORS); SSE fallback if not.
- Background the Even app, wait, foreground: queue restored from SDK storage and socket reconnects.
- 5-minute locked-phone test (Even's requirement).
- Double tap exits cleanly on hardware and passes Even Hub review.
- Card update latency on hardware (backend send -> visible card).
- Manager: the 5 brightness levels are distinguishable on the lens, and a level-4 box stands out from
  level-1 boxes at a glance in restaurant light. Pick the calm level (1 now) on hardware.
- Manager: 8 bordered text containers render without flicker and per-box `textContainerUpgrade` doesn't
  redraw the other boxes; `T12 !` and `12m` fit a 128×64 box with the real font.
- Manager: the minimap rebuild time with 8 containers (3 ms in the simulator) on hardware.
- Manager: tap and swipes reach the app on the minimap page, where only box 1 captures input.
- Role switch from the phone select while the glasses show a card, and the role surviving a background
  reload (SDK storage).
