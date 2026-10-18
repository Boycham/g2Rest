# glasses/ notes (server HUD, voice capture, manager HUD)

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

## Voice capture (draft screen)

Run the relay too: `cd backend/voice && .venv/bin/python relay.py` (needs `ELEVENLABS_API_KEY` and an agent
from `create_agent.py`; fixtures from `make_fixtures.py`). The fake backend proxies capture.* / order.* to it
and shows confirmed orders at `http://localhost:8787/kitchen`.

Debug PCM path (dev server only): open the app with
`?debugPcm=01_order,02_no_soup,03_allergy,04_cancel_dessert`. Each swipe-down capture streams the next fixture
from `backend/voice/fixtures/` (served by the Vite plugin at `/dev-fixtures/`) through the same capture.audio
path in real time, then silence like a quiet mic. Without the param the G2 mic is used (`audioControl`).

Checked in the simulator (0.9.5) against the live relay (Scribe realtime + text-only agent), all four
fixtures, twice: the order builds by seat, `REMOVE s2 soup? tap=yes swipe up=no` and `CANCEL T12 dessert? ...`
appear as the bright bottom line while the order dims, a tap applies each, the final tap sends
`order.confirm`, the card shows `SENT` and the fake kitchen shows `! SHELLFISH s3 / s1 halibut –no butter /
s2 salmon –no dill`. The simulator's own mic: `audioControl(true)` returned false in this VM (no audio
device), which correctly shows `VOICE OFFLINE`.

**End of speech -> draft updated on the glasses** (last voiced 100 ms frame sent -> `textContainerUpgrade`
resolved; logged as `latency ...` and `window.__fsLatency`), 8 runs over the 4 fixtures:
1872, 1926, 1951, 2003, 2032, 2346, 2414, 2550 ms. **Median 2.0 s** (first 5 runs: 2.03 s). About 0.8 s of
it is Scribe's VAD silence before a commit; the rest is the agent turn plus relay and proxy hops. The
upgrade itself takes 0-4 ms in the simulator.

## Sync 1: against the real backend (backend/app), checked in the simulator 0.9.5

```sh
# root .env (gitignored): FS_TOKEN=dev, VITE_FS_TOKEN=dev (same value), VOICE_RELAY_URL=ws://localhost:8790/ws
cd backend && .venv/bin/uvicorn app.main:app --port 8787              # real hub + voice bridge
cd backend/voice && .venv/bin/python relay.py                          # ELEVENLABS_API_KEY in its env only
cd glasses && npx vite
node node_modules/@evenrealities/evenhub-simulator/bin/index.js \
  "http://localhost:5173/?debugPcm=01_order,02_no_soup,03_allergy,04_cancel_dessert" --automation-port 9898
cd web && python3 -m http.server 8000      # organizer: /index.html?token=dev, kitchen: /kitchen.html?token=dev
```

- **URL:** `VITE_BACKEND_URL` + `?token=VITE_FS_TOKEN&role=<picker>&staff=<s1 | m1>` (`src/backend-url.ts`;
  `VITE_FS_STAFF` picks another server). Switching the role on the phone redials with the new role. **The token
  is a dev token and ships in the WebView bundle**: anyone with the `.ehpk` can read it. Fine for the demo,
  not for a real restaurant (that needs per-device credentials). Logs and the phone page show it as `token=…`.
- **Fallback:** `npx tsx dev/fake-backend.ts` still works unchanged; it ignores the query string.
- **Tasks:** a RUN dispatched from `web/index.html` (T1-T4, Ava = s1) shows on the card; tap -> `accepted` and
  tap -> `done` show on the organizer's dispatch board live.
- **Voice through the hub:** one glasses socket; the hub's `app/voice_bridge.py` forwards to `relay.py`. All
  four fixtures (now spoken for **table two**, T2: `floor.json` has no T12) build `T2 · s1 halibut –no butter ·
  s1 chocolate torte · s2 salmon –no dill · s2 soup`; `REMOVE s2 soup?` and `CANCEL T2 dessert?` are tapped;
  the final tap fires it, the glasses get `order.closed` and rebuild the card, and `web/kitchen.html` shows the
  T2 ticket (`ALLERGY SHELLFISH s3`, S1 Pan-Roasted Halibut no butter, S2 Cedar Plank Salmon no dill). Twice.
- **Manager:** a CLEAR for T3 with s1 offline escalated s1 -> s2 after 2 min, s2 -> m1 after 2 min, then 30 s
  unaccepted -> `alert unacked-…`; the glasses showed `! T3 clear task unacknowledged 4m`.

**Organizer dispatch -> card on the glasses** (Dispatch click in `web/index.html` -> card `textContainerUpgrade`
in the simulator console, same clock), 5 runs: 54, 34, 50, 47, 28 ms. **Median 47 ms.**

**End of speech -> draft on the glasses through the real hub** (same measurement as above, now glasses -> hub ->
relay -> hub -> glasses), 8 runs over the 4 fixtures: 2973, 1821, 2331, 1978, 2705, 1619, 2904, 2063 ms.
**Median of the first 5: 2.33 s** (all 8: 2.20 s). Through the fake backend it was 2.0 s; the extra hop costs
little next to Scribe's 0.8 s VAD and the agent turn, and the spread run to run is larger than the difference.

## Not done here

- `order.readback` is parsed but not drawn; `task.bounce` is typed but no gesture sends it yet.
- The relay's order lives per glasses connection: a WebView reload starts a new draft.
- **Manager tap only dismisses locally.** The contract has no alert acknowledgement, so the dismissed alert
  stays open on the backend and comes back if the backend re-sends it. Proposed `alert.ack` in the PR.
- No Organizer role on the phone yet (AGENTS.md lists one); the select has Server and Manager only. The
  organizer is `web/index.html`, which connects with `role=organizer`.
- The minimap draws at most 8 tables (one text container each); more are dropped after natural sort.
- `app.json` whitelists only `ws://localhost:8787` and `http://localhost:8787`. Add the real `wss://`/`https://`
  host before packing for the phone.

## Checked on a real G2 (server HUD, first hardware run, reported by Boyuan)

- **Install path that worked:** pack the `.ehpk` (SDK 0.0.16, `min_app_version` 2.2.10), upload it on the Even
  Hub portal, push it to a Beta group, then install from the phone app's **Me → Beta tester**. The emailed invite
  link said "build expired"; installing from Me → Beta tester worked anyway. Developer Mode / Scan QR never
  appeared in the owner's Even app, so QR dev mode is untested (this corrects the earlier note here, which said
  QR dev mode skipped the whitelist).
- **Network:** the packed build reached the fake backend over a Tailscale IP with plain `ws://`, listed in
  that build's `app.json` whitelist. So packed builds accept a non-TLS `ws://` host when it is whitelisted.
  The committed `app.json` still lists only localhost; add the host you use before packing.
- **Gestures:** tap accept → tap done for all 3 tasks; swipe down → `capture.start`, swipe down again →
  `capture.stop`. The backend received each message within the same second as the gesture.

## HW-PENDING (real G2 + phone)

- Swipe up (queue and back) and double tap on hardware; ring vs temple input.
- Card legibility at each brightness; the dim `ACCEPTED` state is readable; 5-line cap fits the real lens.
- `+N queued` stays flush right on hardware (padding built from pretext widths of spaces).
- Background the Even app, wait, foreground: queue restored from SDK storage and socket reconnects.
- 5-minute locked-phone test (Even's requirement).
- Double tap exits cleanly on hardware and passes Even Hub review.
- Card update latency on hardware (backend send -> visible card).
- G2 mic quality in a noisy room (the real risk); `audioPcm` chunk size/encoding on a real device; mic turns
  off on swipe down, swipe up back, background and exit (the G2 mic LED, if any).
- Manager: the 5 brightness levels are distinguishable on the lens, and a level-4 box stands out from
  level-1 boxes at a glance in restaurant light. Pick the calm level (1 now) on hardware.
- Manager: 8 bordered text containers render without flicker and per-box `textContainerUpgrade` doesn't
  redraw the other boxes; `T12 !` and `12m` fit a 128×64 box with the real font.
- Manager: the minimap rebuild time with 8 containers (3 ms in the simulator) on hardware.
- Manager: tap and swipes reach the app on the minimap page, where only box 1 captures input.
- Role switch from the phone select while the glasses show a card, and the role surviving a background
  reload (SDK storage).
- Sync 1 on hardware: the packed build against the real backend over the LAN/Tailscale host (whitelist it in
  `app.json`), dispatch -> card latency on the lens, and a real-mic order through the hub and relay.
