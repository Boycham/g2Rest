# glasses/ notes (server HUD)

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

## Surprises

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
- `order.draft`, `order.readback`, `alert`, `floor.state` are parsed but not drawn; `order.confirm` /
  `order.cancel_confirm` and `task.bounce` are typed but no gesture sends them yet.
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
