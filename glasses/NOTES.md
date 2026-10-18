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
- Swipe fwd -> queue screen; swipe fwd again -> back to the card. Swipe fwd, then tap -> back to the card.
- Swipe back -> `capture.start` sent, `Listening… (swipe back to stop)` shown; swipe back -> `capture.stop`
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
  (next card), swipe fwd -> queue and back, swipe back -> `capture.start` / `capture.stop`.
- Exceptions: blank at the start of each loop; `VIP seated T7`, then `T3 task unacked 40s`, then
  `! T4 waiting 14m on mains` on top, each as one `textContainerUpgrade` (1-2 ms). With no new message the
  local timer ticked `T3 task unacked 40s -> 50s -> 60s`. Clears drop lines in place; after the last clear
  the screen is blank.
- Tap on exceptions -> `dismissed locally late-t4` (no message: the contract has no ack). The next alert
  moves up.
- Swipe back -> minimap: one `rebuildPageContainer` with 8 bordered text containers (3 ms). After that,
  table changes are per-box `textContainerUpgrade` only (`box 3 upgrade "T3 W\n0m"`, 2-4 ms), no rebuild.
- Late table: `POST /late?table=T2` while on the minimap -> the next `floor.state` upgrades box 2 to
  `T2 !` at brightness 4 in one update (2 ms). Same for T5.
- Swipe fwd -> exceptions again; double tap -> `shutDownPageContainer(1)`, glasses blank.

Unit tests: 55 vitest tests (27 server + exceptions ordering/formatting, minimap layout/brightness, parser
checks for `alert` and `floor.state`).

### Why text containers for the minimap

The SDK has text, list and image containers. A list container swallows swipe fwd (see Surprises), and an
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
- **A list container swallows swipe fwd.** With the queue as a `ListContainerProperty`, swipe fwd only moved
  the selection; no `SCROLL_TOP_EVENT` reached the app, so "swipe fwd again to return" never fired (tap still
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
fixtures, twice: the order builds by seat, `REMOVE s2 soup? tap=yes swipe fwd=no` and `CANCEL T12 dessert? ...`
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
- **Gestures:** tap accept → tap done for all 3 tasks; swipe back → `capture.start`, swipe back again →
  `capture.stop`. The backend received each message within the same second as the gesture.

## Real G2: swipes are forward and back (0.1.5, reported by Boyuan)

- The touchpad swipes run **forward** (toward the eyes) and **back** (toward the ear), not up and down. A
  forward swipe opened Controls, so SDK `up` (`SCROLL_TOP_EVENT`) = fwd and SDK `down` (`SCROLL_BOTTOM_EVENT`) = back.
- Labels only changed: the hint is `fwd: controls` (measured, fits beside `+N queued`), Controls rows say
  `swipe fwd` / `swipe back`, and the draft bars say `tap=yes swipe fwd=no` and `say the table, then swipe
  back`. `GESTURE_EVENTS` in `main.ts` and `MAIN_GESTURES` are unchanged. The voice words `verity up` /
  `verity down` stay as spoken commands.
- Also from that test: long hold inside Controls now goes back to the card (like Close, whose row says
  `hold`); Controls ends with `fwd/back: move · tap: pick · hold: back`. The queue page was cluttered: in the
  simulator nothing overlapped (it is its own page, without the hint or menu rows), but each row repeated the
  card's dish list behind the same `>` / indent marks as the menu, and it never redrew while open. It now
  shows one `T12 · RUN · ! SHELLFISH` row per task, the current one marked, `tap: back` bottom right, and
  updates in place.

## Real G2 against the Vultr host (0.1.6)

The backend and voice relay run on Vultr at `https://45-76-173-44.sslip.io` (PR #12, Caddy, Let's Encrypt).
`app.json` whitelists `https://` and `wss://` for that host; localhost stays for dev. No Tailscale host was
ever in the committed `app.json`, so none was removed.

Build and upload (a person does the upload; the CLI has no upload command):

1. `cd glasses && npm install`
2. `VITE_FS_TOKEN=<the server's FS_TOKEN> npm run pack:vultr` (refuses to run without the token; sets
   `VITE_BACKEND_URL=wss://45-76-173-44.sslip.io/ws`). Writes `glasses/floor-sense.ehpk`, version 0.1.6 (above the 0.1.5 already on the G2).
   The token ends up inside the bundle, so share the `.ehpk` only with the team, and never commit it.
3. hub.evenrealities.com → Floor Sense project → Builds → upload `floor-sense.ehpk` (version 0.1.6) as a
   private build.
4. Push the build to the Beta group and add the tester's email.
5. Phone: Even Realities app (glasses paired) → Me → Beta tester → Floor Sense 0.1.6 → Install. The emailed
   link may say "build expired"; installing from Me → Beta tester works anyway.
6. Launch it from the glasses home screen, pick Server on the phone, and check the phone page shows the
   `wss://45-76-173-44.sslip.io/ws` URL (token redacted) and `connected`.

Simulator 0.9.5 against the server (Vite dev with the same `VITE_BACKEND_URL`, no local backend or relay,
connected as s2 so the real G2 on s1 was left alone):

- `wss://…/ws?token=…` opened first time; no 4401, TLS or CORS errors. `/state` without or with a wrong
  token: 401.
- Task to card (`POST /tasks` CHECK T5 for s2 → card in the simulator screenshot, which slightly overstates
  it): 76.0 / 75.0 / 74.7 / 75.1 / 83.0 ms, median **75 ms**. Tap accept and tap done showed on the organizer page.
- Clip through the server's relay (`conv_task`, 58.7 s, 587 frames, table T5 from the ORDER task),
  `capture.stop` → draft drawn: 4674 / 3280 / 3126 ms, median **3.3 s** (4.0 s locally earlier). The three
  drafts were identical: shellfish on s2, halibut no butter, salmon no dill, `? s3 'the fish'`, the
  anniversary note.
- The deployed 30 s no-accept timer reroutes a task left unaccepted, so a test that pauses moves its task to
  another server (it happened once, to s1). Keep test cycles back to back.
- HW-PENDING: the packed `.ehpk` on the G2 (whitelist enforced by the phone), lens latency over cellular.

## HW-PENDING (real G2 + phone)

- Swipe fwd (queue and back) and double tap on hardware; ring vs temple input.
- Card legibility at each brightness; the dim `ACCEPTED` state is readable; 5-line cap fits the real lens.
- `+N queued` stays flush right on hardware (padding built from pretext widths of spaces).
- Background the Even app, wait, foreground: queue restored from SDK storage and socket reconnects.
- 5-minute locked-phone test (Even's requirement).
- Double tap exits cleanly on hardware and passes Even Hub review.
- Card update latency on hardware (backend send -> visible card).
- G2 mic quality in a noisy room (the real risk); `audioPcm` chunk size/encoding on a real device; mic turns
  off on swipe back, swipe fwd back, background and exit (the G2 mic LED, if any).
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

## Conversational capture (rolling minute), checked in the simulator 0.9.5 against the real backend

Owner's design (2026-10-18): the server talks normally with the table; a **swipe back sends the last 2 minutes**.

- **Mic rule (exactly):** while the Server role is on, the mic records constantly into a rolling 120 s buffer
  that lives only in WebView memory (`src/clip.ts`, a fixed ring of 1200 × 100 ms frame slots, 3.84 MB). Anything older
  than 120 s is overwritten continuously. Only a clip ever leaves the device, and only on a swipe
  down. Nothing is written to SDK storage, browser storage or disk. The relay holds the clip in memory, hands
  it to Scribe and drops it; it keeps the extracted order only. Switching to Manager or exiting turns the mic
  off and clears the buffer. The phone page says `mic: last N s in memory`.
- **Gestures:** swipe back on the card or the draft = send the last 2 minutes (`capture.start{mode:'clip'}`,
  the frames back to back, `capture.stop`). Tap on the draft = accept a pending line, else send (refused while
  `TABLE?`). Swipe fwd = reject a pending line, else back to the card. Double tap = exit, as before.
- **Table:** an accepted ORDER task (`ORDER · T3`, then `swipe back once they have ordered`) sends its table;
  the hub also falls back to the server's open ORDER task. Without one the draft shows `TABLE?` and the bar
  says `TABLE? say the table, then swipe back`; saying "that was table two" and swiping again binds T2.
  Firing the order marks the ORDER task done.
- **Draft:** allergies on top, `T3 … tap = send` (or `Reading last min…` while processing), order by seat,
  then `?` lines and `note: anniversary · no rush on mains`. Order lines fold into `… N more` first, so `?`
  lines never drop off the lens.
- **Debug path:** `?debugPcm=conv_task` fills the buffer with the fixture (instead of the mic) and refills it
  after each clip; `?debugPcm=conv_notable,conv_tableless` gives the TABLE? → "table two" flow.
- **Role on connect (real-G2 bug):** the packed `VITE_BACKEND_URL` carried `role=server&staff=s1`, which
  `backendUrl` kept, so the glasses were always server Ava. The picker now always sets role and staff, and a
  switch redials (`BackendSocket.redial`); `src/socket.test.ts` checks both.

Runs (simulator, real hub + relay, fixtures from `make_fixtures.py`, `web/kitchen.html` open):
- ORDER task T3 + `conv_task` (58.6 s, two voices, small talk, one bystander line, "the fish"): draft
  `! SHELLFISH s? / T3 tap = send / s1 halibut –no butter / s2 salmon –no dill / ? s3 'the fish': halibut or
  salmon / note: anniversary · no rush on mains`; tap fired it, the kitchen showed the T3 ticket, the ORDER
  task went `done`. Small talk and the bystander line added nothing in every run.
- Table-less: `conv_notable` → `TABLE?` draft, tap refused, kitchen showed the `TABLE?` draft forming;
  `conv_tableless` ("that was table two") → T2, tap fired it to the kitchen.

**Swipe back → draft on the glasses** (swipe input → `textContainerUpgrade` of the clip's draft, simulator
console clock), 58.6 s clip, 5 runs: 4271, 3903, 3866, 4082, 4017 ms. **Median 4.02 s.** Split (relay log):
upload is local and immediate, Scribe batch 1.15-1.37 s for 58.7 s of audio, the agent turn (claude-haiku-4-5)
about 2.5-3 s. Table-less clips (29-31 s): 2.40, 2.50, 2.63 s.

Known misses (5 runs, same fixture): seats right 5/5, but SHELLFISH landed on s1 instead of s2 in 4/5 (all
guests share one TTS voice, so diarization can't help); once the server's "some bread" became burrata `–no
bread` (the clip-words guard only checks the words were said).

HW-PENDING (conversational capture):
- Whether the mic keeps running with the phone locked or the Even app backgrounded (the app leaves it on at
  foreground exit), and the battery cost of always-on capture on the G2 and the phone.
- Clip upload time over phone Bluetooth/LTE (1200 frames, 3.84 MB) and the real-mic transcript quality in a
  noisy room with real, different guest voices.

## Clip summary, answers and table by voice, checked in the simulator 0.9.5 against the real backend

Real hub (`backend/app`, restarted after the `contract.py` change: the old process dropped
`voice.command {intent: "table"}`) + relay with the order and talk agents. Each run is a fresh simulator.

- **Layout (`src/draft.ts`, pretext-measured):** order lines, `── table said ──`, the summary (wrapped, 2 lines
  max), then one line per answer: `s2 pork belly have sesame? → yes, pork belly has sesame`, or the menu-gap
  line `? s1 asks gluten-free bread: not in menu data`. Overflow goes to pages: `swipe fwd = more 1/2`, then
  `2/2 swipe fwd = done`. Tap sends only `order.confirm {orderId}`; summary and answers never reach the kitchen.
- **Answers only** (`conv_answers_only`, 24 s, no dishes): `TABLE?`, separator, summary and four answers, no
  order lines; draft 3.80 s, summary and answers 3.95 s after the swipe (1 run).
- **Swipe back → card, median of 5** (`latency swipe back -> ...` in the console):

| Clip | → order draft | → summary + answers |
|---|---|---|
| 60 s (`conv_questions`): 4048, 3363, 3582, 3746, 4149 / 4532, 4819, 4807, 4985, 4881 ms | **3.75 s** | **4.82 s** |
| 120 s (`conv_2min`, this branch): 5734, 5177, 5463, 5821, 5289 / 6941, 6570, 6587, 6937, 6699 ms | 5.46 s | 6.70 s |

  Relay split, 120 s vs 60 s: batch Scribe 2.32-2.80 s vs 1.45-1.59 s; clip stop → `set_order` 4.96-5.59 s vs
  3.24-4.04 s (the agent reads 33 turns instead of 17). Old main (order only, 58.6 s): 4.02 s.
- **Table by voice** (`?debugPcm=conv_notable&say=silence_20,verity_table_12,verity_table_four,silence_8,verity_table_two`):
  `TABLE?` draft → "verity table twelve" → `? T12: no table 12` (still `TABLE?`) → "verity table four" →
  `T4 … tap = send` with `? Heard: table T4` and no new clip → tap → `order.closed fired` → "verity table two"
  → `T2: already sent` on the main card. The override of an ORDER task's table (`Table T3 → T4`) and the
  table said last in a clip (`conv_table_last` → T4) were checked against the relay (`tests/test_relay.py`,
  relay bench), not in the simulator.
- Known: the talk agent numbers guests on its own, so an answer's `s2` can differ from the order's seat for
  the same guest when the two agents count differently (seen once in the 120 s run).
- HW-PENDING: the extra lines' legibility on the lens; "verity table N" with a real voice in the room.

## Voice commands, checked in the simulator 0.9.5 against the real backend

`?debugPcm=conv_notable&say=verity_accept,verity_decline,verity_done` plays TTS command fixtures into
the command stream (4 s apart) as if the server said them. `src/voice.ts` maps intents to the gesture
frames (`task.accept` / `task.bounce` / `task.done`; the hub checks the socket's staff). Commands act at
once; the card shows `Heard: <command>` for 3 s. The backend decides: a refused frame comes back as
`task.rejected` and its `reason` goes on the card as is (no local "Can't ..." guesses).

### Gesture map (one place)

`MAIN_GESTURES` in `src/controls.ts` says what each gesture does on the main card (moving clip is one
line there); `GESTURE_EVENTS` in `src/main.ts` maps OS events to gestures.

| Gesture (main card) | Action | Voice |
|---|---|---|
| Tap | accept, then done; confirms a popup or sends the draft | `verity accept` / `verity done` / `verity confirm` |
| Swipe fwd | open Controls | `verity menu` / `verity controls` / `verity up` |
| Swipe back | clip the last 2 minutes | `verity clip` / `verity down` |
| Long hold | handoff: `Confirm handoff?` popup, then tap | `verity handoff [name]`, then `verity confirm` |
| Double tap | exit dialog (`shutDownPageContainer(1)`, Even Hub review rule) | none |
| Controls → Queue | queue page (`tap: back`; any tap or swipe goes back) | `verity queue` |
| Controls → Decline / Revert | `task.bounce` / `task.revert` | `verity decline` / `verity revert` |
| Controls → Set table | bind the unsent draft to table N | `verity table N` |
| Controls → Close, or hold in Controls | back to the card | `verity back` |
| (popup open) | cancel it | `verity nevermind` |

In Controls swipe fwd/back move the `>` row and stop at the ends; a tap picks the row; hold, Close or "verity
back" close it (swipe back doesn't: it's clip on the card). The last line is `fwd/back: move · tap: pick ·
hold: back`. The always-on `fwd: controls` hint is the card's last line, right-aligned (sharing it with
`+N queued`), measured with pretext (`controls.test.ts`).

- Handoff sends `task.handoff {taskId, to?}` only after the popup is confirmed; "verity revert" sends
  `task.revert` and the un-accepted `task.updated` that answers it isn't replayed as a lost accept.
- Unknown words after "verity" go to Gemini on the relay; unmapped or failed: `Didn't get: <words>`
  (with `(timeout)` / `(no key)` when Gemini wasn't reachable).
- End of command → `Heard:` on the glasses: median 0.61 s of 5 (see backend/voice/NOTES.md).
- No `task.command` frame: the gesture frames already cover the task intents, and navigation is local.
- HW-PENDING: the command stream with the phone locked/backgrounded, and battery of streaming the mic.
- HW-PENDING: long hold (SDK `LONG_PRESS_EVENT` 9) on the real ring/temple; AGENTS.md still says there
  is no long press, and the simulator may not send it.

## Manager exceptions and the 86 banner, checked in the simulator 0.9.5 against the real backend

Backend `FS_TOKEN=dev FS_COURSE_WAIT_SEC=15` (shortened so the course wait shows within a minute), Vite, simulator
with `--automation-port 9898`, role switched on the phone page.

- **Manager:** seated T4, fired a salmon (`/tools/add_item` + `/orders/{id}/confirm`), seated T7 with `vip: true`,
  `POST /menu/risotto/86`. The exceptions screen showed, brightest first:
  `! T4 waiting 10s on mains` / `86 risotto` / `VIP seated T7` (`exceptions upgrade true 2.0 ms`). Plate up
  (`/pass/up`) cleared the course wait and `un86` cleared the 86 line; only `VIP seated T7` was left.
- **Server (s1):** `POST /menu/halibut/86` put `86 halibut` on the card's top line, above the RUN
  (`card upgrade true 2.0 ms`); `POST /menu/halibut/un86` removed it (`1.0 ms`). The same `add_item` for risotto
  while it was 86'd returned the error and the draft got `? s1 risotto 86'd`.
- **Widths** (pretext, card text width 564 px): `86 halibut` 88, `86 halibut, risotto, salmon, chocolate torte`
  363, `VIP seated T7` 122, `! T4 waiting 14m on mains` 216, `! T4 waiting 2h00 on desserts` 254.
- Under 2 minutes `{elapsed}` rounds down to 10 s steps, so a 15 s wait reads `10s`; at the 12-minute default it
  reads `12m`.
- HW-PENDING: the 86 line and the three-line exceptions list on a real G2 (brightness of the `warn` vs `info` lines).


## "Verity is thinking": processing animation, checked in the simulator 0.9.5 against the real backend

- **What shows:** from swipe back / "verity clip" until the order draft lands, the draft's bottom bar reads
  `Verity: processing.` → `..` → `...`; once the order shows, the bar keeps a smaller `summary.` → `...` until
  the summary and answers arrive (or 15 s pass, then it just stops). The same `Verity: processing...` line runs
  while Gemini maps unknown words after "verity" (relay sends `voice.mapping {words}` first), in the card
  banner or the draft bar; `voice.command` / `voice.unknown` stops it, and after 5 s with neither the glasses
  show the existing `Didn't get: <words> (timeout)`. A clip timeout (30 s) still shows `VOICE OFFLINE`.
- **Rate: one update every 400 ms (2.5 a second).** The SDK docs give no number for a BLE update limit; they
  say to update a card in place with `textContainerUpgrade` and keep `rebuildPageContainer` for screen
  changes. So each tick rewrites only the bar container (`BAR_ID`) with `textContainerUpgrade`, the main text
  is left alone, and nothing runs per frame. Console per 120 s clip: 16-18 `busy upgrade` lines, median gap
  402 ms, one `rebuild draft` (entering the screen), 4 `draft upgrade` (content changes).
- **Swipe back → card on the 120 s clip (`conv_2min`), median of 5**, runs interleaved with main at `addead7`
  (no animation) on the same relay and hub:

| Build | → order draft | → summary + answers |
|---|---|---|
| main `addead7`: 7474, 5872, 5658, 5591, 4864 / 7023, 7103, 6851, 6895, 6263 ms | 5.66 s | 6.90 s |
| this branch: 7535, 6601, 5210, 5686, 5797 / 7240, 7508, 6807, 7019, 7189 ms | 5.80 s | 7.19 s |

  The 0.1-0.3 s gap is within run-to-run spread (4.9-7.5 s); the animation adds no backend work. In run 1 of
  both builds `set_talk` finished before `set_order`; main then lost the summary, this branch keeps it.
- Seen, not changed here: `Reading last 2 min…` on the draft's top line wraps to a second line in the
  simulator (pretext says it fits); same on main.
- HW-PENDING: whether 2.5 updates a second is smooth and costs no input lag over real BLE.
