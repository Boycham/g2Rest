# Floor Sense (LA Hacks, Oct 17-18 2026)

Read this whole file before starting any task in this repo. It is the standing brief for every Devin session.

## The project

Floor Sense puts the floor of a high-end restaurant on Even Realities G2 smart glasses.

- **Server view (the core demo).** One task card at a time ("RUN · T12 · 2× halibut, seats 1+3", "+2 queued"
  in the corner). The screen is blank when nothing needs the server. Allergies always go on the top line.
- **Voice order capture.** The server takes a table's order out loud as usual. ElevenLabs speech-to-text plus an
  ElevenLabs agent builds the order live on the glasses, by seat: add and remove dishes, record alterations
  ("no onions"), pin allergies. The agent can only *propose* sending or cancelling an order; the server taps
  on the glasses to actually do it. The mic runs only while an order is being taken.
- **Manager HUD.** Exceptions only by default ("T4 waiting 14 min on mains", "task unacknowledged 60 s").
  Swipe for a floor minimap: tables as boxes with a status glyph and a timer, brightness for urgency. The G2
  has no camera, so this is a minimap, not AR.
- **Organizer.** The phone screen of the same Even Hub app (role picker: Server / Manager / Organizer) plus web
  pages for dispatch, floor plan and the kitchen. The organizer sends tasks and watches them; only the assigned
  server accepts, finishes or bounces a task, on their glasses.
- **Task routing.** Gemini (Flash-Lite, about a second) picks which server gets each new task from the table's
  section and everyone's open tasks. The fixed rules take over if Gemini is slow, down or unset, and they still
  run escalation (next server after 30 s unaccepted, then the manager) and the run planner below.
- **Task timing.** The backend times every task from accept to done per server (`GET /stats`, for the
  manager dashboard and Gemini's context). A task accepted but not done after 5 minutes alerts the manager
  and is rerouted to someone else; a RUN is only flagged, since the server is holding the plates.
- **Run priority.** Food is scored: appetizers first, hot beats cold, hot plates rise fastest while they wait,
  hot plates for nearby tables are paired into one trip (max 3 per server), cold never holds up hot, and a
  table's whole course goes out together.
- **Dinner-rush simulator.** Replays a two-hour service in about 3 minutes to drive the demo, once
  first-come-first-served and once with priority scoring, so we can show the hot-food wait times side by side.

The full plan is the Claude Doc "Floor Sense — Build Plan". Your prompts come from it; if a prompt and this file
disagree, the prompt wins for that task, and say so in your PR.

### Who owns what

Two coders work in parallel, in separate folders, so there are no merge conflicts.

| Lane | Owner | Folders | Stack |
|---|---|---|---|
| Glasses + voice | Coder B (Devin works here) | `glasses/`, `backend/voice/` | TypeScript + Vite, `@evenrealities/even_hub_sdk`; Python for the voice spike |
| Restaurant brain | Coder A | the rest of `backend/`, `web/`, `sim/` | Python FastAPI, WebSocket hub, task state machine, Gemini task router |

**Only change files inside your lane's folders.** If you need something from the other lane (a new message
type, a field, an endpoint), don't build it there: write what you need in your PR description and, if
necessary, stub it on your side behind a clearly named fake.

The glasses and backend talk through a frozen **message contract** (and a menu file format). Never change the
contract on your own. If it's missing something, propose the change in the PR.

### Judging

Judges score Technical Depth, Product Thinking & Impact, Originality & Insight, and Execution & Polish, each
1-4. We are aiming for 4s, which means: it works on real glasses, it's measured (latency, wait times), it's
quiet and glanceable, and the rough edges are gone. Even Realities' own rule: one interaction that feels natural
on G2 beats a long list of features.

## Event rules (breaking these means disqualification)

- All code, data (menu, floor plan, reservations, demo script) and designs are created in this repo during the
  event. Don't copy from other projects. Public SDKs, Even's templates and npm/PyPI packages are fine.
- List every framework and library you use in `README.md`.
- Keep `AI_USAGE.md` current: how Devin and Claude built this, and how ElevenLabs is used in the product. It
  is pasted into Devpost; uncredited AI use is disqualifying.
- Fictional data only. Record only people who agreed. Never store or commit audio.

## Commit practices

The git history is our evidence that the work happened at the event. Many small commits beat a few big ones.

- **Commit after every logical change that works** (builds, runs, or passes its check). One concern per
  commit. Never sit on more than about 30 minutes of uncommitted work.
- **Work on a branch and open a PR** for each prompt (`devin/<short-topic>`). Merge without squashing: the
  granular history is the evidence.
- **Message format:** Conventional Commits, imperative mood, subject at most 72 characters, no trailing period.
  `type(scope): what changed`
  - types: `feat` `fix` `perf` `refactor` `test` `docs` `chore`
  - scopes: `glasses` `voice` `backend` `web` `sim` `data` `demo` `infra`
  - e.g. `feat(glasses): show allergy line above the dish list`
- **The body says why, not what.** For performance or latency changes, put before/after numbers in the body
  (`end of speech to tool call, median of 5: 1.9 s -> 0.8 s`).
- Keep any AI co-author trailer your tooling adds. It is part of the AI-use disclosure.
- **Stage explicit paths** (`git add glasses/src/card.ts`), never `git add -A` or `git add .`. Read
  `git diff --cached` before every commit.
- **Secret check before every commit.** Both commands must print nothing; read every hit before overriding:
  ```sh
  git diff --cached --name-only | grep -E '(^|/)\.env' | grep -v '\.env\.example$'
  git diff --cached -U0 | grep -nE 'sk_[0-9a-f]{32,}|xi-api-key|AIza[0-9A-Za-z_-]{35}|sntrys_|[0-9a-f]{40}|PRIVATE KEY'
  ```
  If a key ever lands in a commit, say so in the PR so it gets rotated. Rewriting history doesn't help once
  it has been pushed.
- **Never commit:** `.env` files (only `.env.example`, with names and no values), `*.ehpk`, `dist/`,
  `node_modules/`, audio (`*.wav`, `*.pcm`, `*.mp3`, `*.m4a`), or runtime state (live orders, task logs).
- Never force-push `main`, never use `--no-verify`, never amend a pushed commit.

## Coding practices

- **Keep it small.** The simplest thing that works on the glasses. No framework or abstraction until a second
  use needs it. One module per concern.
- **Rules live in code, not prompts.** Menu validation, allowed alterations, "confirm and cancel need a tap",
  card length limits and run priority are enforced in code and tested. The LLM proposes; code decides.
  A dish not on the menu returns an error with the closest names; an alteration not allowed for that dish is
  flagged, never silently applied.
- **No LLM call in the card path.** Showing or updating a task card must not wait on a model.
- **Tool errors go back to the agent as results**, never crash the session. Validate every tool argument.
- **Every external call** (ElevenLabs, backend) has a timeout and a visible failure state on the glasses.
- **Secrets:** read keys from environment variables (`ELEVENLABS_API_KEY` is in Devin's secrets). Keys stay on
  the backend: never in the WebView bundle, logs, commits or PR text.
- **Tests:** `pytest` for Python, `vitest` for TypeScript. Test the guards and the state machine without
  calling ElevenLabs. Don't skip or delete a failing test to get green.
- **Don't call anything done until you've seen it work:** a passing test, a simulator screenshot, or a run log.
  Put the numbers (latency, wait times) in `NOTES.md` in your lane's folder, along with surprises and anything
  that still needs checking on real hardware (mark it `HW-PENDING`).
- **Check current docs** for model IDs, endpoints, SDK versions and message shapes before coding. Don't rely on
  memory; write what you confirmed, with links, in `NOTES.md`.
- TypeScript: `strict` on, no `any` in the contract types. Python: 3.11+, type hints, formatted with `ruff`.
- Prefix your own log lines (`[fs]`) so they can be filtered from the SDK's noise.

## G2 and Even Hub facts (checked on the simulator)

The full detail (SDK, simulator, voice, hosting, hardware checks) is in the **`g2-glasses-integration` skill**
at `.agents/skills/g2-glasses-integration/`. Read its `SKILL.md`, then the file for the area you're touching,
before any work in `glasses/` or `backend/voice/`. The short version:

- **Display:** 576×288, monochrome green, 5 brightness levels. About 63 characters per line of average English
  in a full-width card. Measure text with `@evenrealities/pretext` instead of guessing.
- **Input:** tap, double tap, swipe up, swipe down. **There is no long press.** Swipes arrive as scroll events
  on the event-capture container, with no source, so ring and temple can't be told apart. Only one container
  per page captures input.
- **Our gestures:** tap = accept, then tap again = done. Swipe down = take an order. Swipe up = queue.
  Double tap = exit.
- **Double tap on the root page must call `shutDownPageContainer(1)`.** Anything else gets the app auto-rejected
  by Even Hub review. Never reuse double tap for anything else.
- **Rendering:** update cards in place with `textContainerUpgrade` (no flicker). Use `rebuildPageContainer`
  only to switch screens. Call `createStartUpPageContainer` exactly once per app run.
- **Audio:** the mic streams PCM 16 kHz, signed 16-bit little-endian, mono, in 3200-byte (100 ms) frames. The
  G2 has no speaker.
- **Network:** every host you call must be listed in `app.json` (`https://` and `wss://`), and CORS still
  applies. Confirm WebSocket support early; keep server-sent events as a fallback.
- **Background:** when the phone app goes to the background, the plugin reloads in a hidden WebView. Save state
  with the SDK storage (`bridge.setLocalStorage`), not browser `localStorage`. On the foreground event,
  reconnect the socket. Even asks for a 5-minute locked-phone test.
- **SDK:** scaffold from `npx degit even-realities/evenhub-templates/asr glasses`. Pin the SDK version
  explicitly (for 0.0.x, `^` pins exactly); after an upgrade restart Vite with `--force`.
- **Packing:** `npx evenhub pack app.json dist -o floor-sense.ehpk`. The app name must be at most 20 characters
  and can't contain "Even". Uploading to Even Hub is manual and done by a human.
- **Simulator:** run `evenhub-simulator` with its automation port to screenshot, send input and read the
  console. Restart it after every app or server restart. Its mic may not hear the laptop speakers, so always
  build a debug path that injects text or streams a PCM file instead of the mic.

## Speech

- ElevenLabs Scribe for speech-to-text; an ElevenLabs agent (text-only mode) turns committed transcript
  segments into tool calls. Generate test audio with ElevenLabs text-to-speech into a gitignored `fixtures/`
  folder rather than using a microphone.
- When closing a stream, send the close message and trailing silence and wait for the provider to close, or
  the last words are lost.
- Restaurant noise is the real risk. Measure accuracy on noisy audio, not only clean audio.

## When you need a human

Even Hub uploads, phone installs, pairing the glasses, recordings and new accounts need a person. Stop and
write numbered steps with the exact commands in your PR or session, then wait. Ask before spending money or
creating cloud servers.

## When you finish a task

Open a PR that says what works, what doesn't, the numbers you measured, anything `HW-PENDING`, and any change
you need from the other lane or the message contract.
