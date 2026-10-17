# 05. Lessons already learned

Facts and gotchas found during simulator practice. Each is stated as what to do. "HW-PENDING" means it has
never been checked on a real G2.

## Even G2 SDK and Even Hub

- **Use Even's Claude Code plugin skills** (`everything-evenhub`: glasses-ui, handle-input, device-features,
  font-measurement, test-with-simulator, build-and-deploy, sdk-reference). Their files live under
  `plugins/everything-evenhub/skills/`; find them with `find <marketplace> -name SKILL.md` instead of guessing.
- **Read Even's own testing and shipping docs (hub.evenrealities.com) before choosing gestures or behaviour.**
  That is where the auto-reject rules are.
- **Scaffold** with `npx degit even-realities/evenhub-templates/asr <dir>`. The template's speech-to-text file is
  a stub that throws; it has no vendor code.
- **SDK version:** 0.0.16 was the latest; `zOrderIndex` and image LZ4 need 0.0.12+. The template pinned 0.0.10
  (for 0.0.x, `^0.0.10` means exactly 0.0.10), so upgrade explicitly. After an SDK upgrade, restart Vite with
  `--force` or it keeps serving the old cached SDK.
- **Packing:** `npx evenhub pack app.json dist -o <name>.ehpk --sdk-ver <sdk>`. Pack raises `min_app_version` to
  the SDK's floor (0.0.16 → Even app 2.2.10); set it in `app.json` to match. `pack -c` prints nothing either
  way, so it tells you nothing. Beta installs fail if `min_sdk_version` is above the tester's firmware.
- **The CLI has no upload command** (only login, init, pack, qr). Upload is manual: hub.evenrealities.com →
  project → Builds → upload → push to a Beta group containing your email → phone: Even Realities app → Me →
  Beta tester → Install → launch from the glasses home screen. `evenhub login` is interactive.
- **The phone app hides Beta tester / Even Hub without paired glasses.** That is why the first hour is "borrow a
  G2 and pair it". Private builds in Developer Mode are the faster loop for smoke tests; Beta is the
  reviewer-parity path and the only way onto other phones.
- **Network:** calls only work to hosts in the `app.json` network permission (`https://` and `wss://` of your
  host, exactly the hosts you call). `pack` rejects an empty whitelist. CORS still applies on top.
- **Review rule:** root-page double tap must call `shutDownPageContainer(1)`. Using `0` or a custom exit UI gets
  the app auto-rejected. Never reuse double tap for anything.
- **No long press** exists (the event types are click, scroll top, scroll bottom, double click, lifecycle, IMU).
- **Gesture events:** tap arrives as a sys event with `eventType` undefined (= click); double tap as 3; swipes
  arrive as text events (scroll top / scroll bottom) on the event-capture container **with no event source**, so
  ring vs temple can't be told apart on swipes. Only one container per page captures input.
- **Display:** 576×288. With 27 px lines and a 1 px border and 6 px padding, the card's inner width is 562 px:
  about 63 characters per line of average English. Term + 2 definition lines ≈ 126 chars (worst case ~83 with
  wide letters), so keep definitions ≤ ~110 chars and check at runtime with Even's text-measurement package
  (`@evenrealities/pretext`). Three lines need a ~96 px box.
- **Showing/hiding a card** with `rebuildPageContainer` took 1–6 ms on the simulator; Even's docs warn it can
  flicker on hardware (HW-PENDING). Updating a text line in place is ~2 ms.
- **Call `createStartUpPageContainer` exactly once per app run.** Restart the simulator after app changes.
- **Persistence:** browser `localStorage` does not reliably survive restarts inside the Even app. Use SDK storage
  (`bridge.setLocalStorage` / `getLocalStorage`). Persistence across a real app restart is HW-PENDING.
- **Lifecycle:** on the foreground event, reconnect the socket and re-enable the mic. Even asks for a
  "5-minute locked-phone test" before submission.
- **Logs:** the SDK logs every event, including each audio frame's full PCM bytes, ten times a second. Prefix
  your own log lines and filter by the prefix. On Beta builds, console logs show in the phone app's Developer
  Mode console (don't log secrets); crashes don't auto-report (another reason for Sentry).
- **Audio:** PCM 16 kHz, signed 16-bit little-endian, mono, 3200-byte frames (100 ms). G2 has no speaker.

## Simulator

- Run it with an automation port so an agent can screenshot (`GET /api/screenshot/glasses`), send input
  (`POST /api/input`) and read the console (`GET /api/console`). No `evenhub login` is needed for it.
- It uses the laptop mic (`--list-audio-input-devices`, pick one with `--aid`). It supports tap, double tap,
  swipes and the mic; not long press, ring source, device status, IMU, real fonts, or the exit dialog
  (`shutDownPageContainer(1)` just blanks the display).
- **After every server restart, restart the simulator.** Otherwise it keeps showing cards but silently stops
  delivering gestures, or stops reconnecting (background throttling).
- Its console is a ring buffer flooded by audio frames and keeps old entries: only read entries newer than the
  start of your run.
- The simulator mic may not hear speech played from the laptop speakers (especially with headphones attached).
  Build a debug path that injects text, and one that streams a WAV file, into the live session.

## Speech-to-text

- **Deepgram nova-3** live streaming worked: linear16, 16 kHz, interim results, diarize, keyterms.
- **Noise cliff:** on synthetic voices, 10/10 terms in quiet, 7/10 at about +2 dB SNR, and **nothing at all** at
  0 dB or below (empty transcript). Real human voices in a ~500-person hall were never measured. Plan for it.
- Keyterm prompting made no difference on clean synthetic speech; one later synthetic dry run suggested it helps
  (0.72 vs 0.61 recall). Neither is evidence. Turn it on; measure at the event if possible.
- **Rare words get misspelled** ("chiffonade" → "chaffonade") and then never match. Add likely spellings as aliases.
- **Close the stream properly:** send the close message, keep the socket open until the provider closes it, and
  send ~2 s of trailing silence, or the last sentences are lost. (A benchmark once scored 3/10 for this reason.)
- Keyterms are set when the stream opens; new terms need a reopen to be boosted.
- ElevenLabs Scribe was never tested. Compare it on the same clip before switching.
- **Misheard terms are the real matching problem, not the matcher.** Don't train a model for it. Fix it with
  Gemini-generated aliases at pack-build time plus sound-alike matching (Double Metaphone + edit distance over
  1–3-word windows). Details in [04](04-ARCHITECTURE.md).

## LLM in the live path: latency and cost

- String matching shows a card **2–9 ms** after a sentence. A Gemini lite call before each card would add
  **0.6–2.8 s** normally and **6–8 s** when it stalls.
- Cost is not the constraint; quota and latency are. At `gemini-3.5-flash-lite` paid rates ($0.30 per million
  tokens in, $2.50 per million out), a per-card check for a 1-hour meeting (at most ~120 cards, ~50k tokens) is
  about $0.03. Scanning every transcript chunk (~500 calls, ~1M tokens) is about $0.35 and can use up a
  free-tier daily quota. Token counts are estimates from prompt sizes, not measured.
- So: no LLM call before any card. Use Gemini for ambiguous terms (show the card first, refine it after), the
  post-meeting scan for terms that were missed, alias generation, and the async jobs (agent, recap,
  "used correctly?").

## Gemini

- **Availability is the biggest risk.** Larger flash models returned 503 "high demand" or 429 most of the time
  on some days, and one call hung 290 s. Lite models (`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`) answered
  reliably in ~0.6–3 s. Model IDs change: read the current list in the Gemini docs at the event.
- **Every call:** a timeout, a fallback chain of several models, "sticky" preference for the last model that
  worked, and **hedging** (if the first model hasn't answered in ~2 s for live calls or ~8 s for agent turns,
  start the next model in parallel; first answer wins). Hedging cut a simulated stall from 11.3 s to 6.8 s
  median; lite-first plus a 20 s turn timeout cut agent runs from 56.5 s to 28.8 s median.
- **Free tier:** Google Search grounding returned 429 on every model. Don't depend on it; if web search is needed,
  a keyless HTML search endpoint worked as a fallback. Many big sites return 403 to server fetches.
- **One success is not a test.** Run agent flows several times before calling them done.
- Cost is tiny (cents per meeting-hour on lite models); free-tier quota is the real limit.

## Making the agent reliable

- **Verify, don't prompt.** The prompt said "flag conflicting sources" and the model ignored it 3 of 5 times.
  A `search_sources` tool plus a server-side guard (reject a proposal when another document defers the term,
  e.g. "see X", "TBD", "missing") made it reliable. Keep guards narrow and read what they matched (a loose
  "see" pattern falsely flagged a normal sentence).
- **Check every model output in code:** verify each quote exists in its source file, enforce word/char limits,
  validate tool arguments.
- **Tool errors go back to the model as results.** One malformed tool call (missing argument) once crashed the
  whole agent.
- **Self-check before finishing:** small models sometimes stop early; nudge the loop to finish and produce the
  "Next:" step.
- **Forbid everyday-word aliases** in extraction (the model proposed "top", "clear", "spoon in" as aliases, which
  would fire constantly). The human review catches the rest.
- Say in the prompt what the agent can't do, or it will claim it did things it can't.
- Return every tool call to the UI so the user can see the steps (Workday transparency).

## Sentry

- `@sentry/node` v11: tracing and logs work with no extra option (`Sentry.logger.*`). `googleGenAIIntegration`
  records Gemini calls as AI spans; set it not to record inputs or outputs.
- `@sentry/nextjs` v11 moved `withSentryConfig` to `@sentry/nextjs/config`.
- **Start a new trace per glasses session**, or every log from every session lands in one trace.
- Real stories from practice, to look for again: a primary model timing out twice made a recap take ~45 s
  (logs showed two fallback warnings 12 s apart → move live calls to the lite model); `Buffer.concat` of the
  whole audio window on every 100 ms frame blocked the event loop (spans of 51 ms) → a fixed ring buffer
  (p95 per frame 1.27 ms → ~0).
- Read the data back (Sentry MCP or the UI) to prove each product works, not just that it's switched on.
- Optional `SENTRY_AUTH_TOKEN` for source maps.

## Paper (if entered)

- The Paper MCP needs the Paper desktop app running.
- Set colour and font on **each text node** (or use tokens); the artboard's colour isn't inherited, so text can
  render invisible.
- Exports may land in Downloads: copy them into the repo immediately.
- Use the file id returned by create/open, not one from the file list.
- Real agent data changed the design (more cards, a long plan): include a data-heavy artboard.
- Measure contrast with a script before writing ratios down.
- A direction that worked: one chosen mood, one accent used only as a fill, monospace "evidence" blocks for
  sources and quotes, a dashed (not coloured) "not sure" state; G2 cards in the display's one colour on black.
- Build the companion's CSS tokens directly from the Paper nodes and show side-by-side screenshots.

## Process mistakes not to repeat

- Confirm hardware and accounts before planning tests that depend on them.
- `mkdir -p` a log directory before redirecting into it. Don't use GNU `timeout` on macOS. `sleep` may be
  blocked in agent shells: poll a done-file instead, with a time limit, not an iteration counter.
- Wait for the server's health endpoint before running tests.
- Reset state (learned terms, cooldowns) before each end-to-end run, or the first card is swallowed.
- Mute the mic in scripted tests (room noise resets the quiet timer).
- Grep the route table before calling an endpoint; check the machine-readable API spec before saying a
  capability is missing.
- React: an arrow effect that returns a value is treated as a cleanup function and crashes the page. Use
  braces. Click through the UI in a real browser before calling a screen done.
- Log caught errors locally too, not only to Sentry.
- Open long URLs for the user with `open '<url>'`; copied wrapped URLs pick up spaces.
- The Chrome extension browser can't open localhost; a headless Chrome over CDP worked. Chrome's minimum window
  width is ~500 px, so render mobile screenshots in a 390 px iframe.
- Port 3000 may be taken (Docker); pick ports up front.
