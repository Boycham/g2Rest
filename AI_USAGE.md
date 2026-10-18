# AI usage

Floor Sense was built at LA Hacks (Oct 17-18, 2026) by two humans directing two AI coding agents:
**Devin (Cognition)** and **Claude Code (Anthropic, Claude Opus 5.5)**. The humans wrote the plan, set the
product rules, briefed every session, reviewed the work and did everything that needs a person (Even Hub
uploads, installing on the phone, wearing the G2). Nearly all code, tests,
docs and fictional data in this repo were written by the two agents. Commits keep the agents' co-author
trailers (`Devin AI`, `Claude Opus 5.5`) as part of this disclosure.

The only thing made before the event is the Claude skill in `.agents/skills/g2-glasses-integration/` (notes
on building for the G2, no code), which the owner made beforehand.

## What Devin built

Devin built every lane it worked on, each from a prompt, with its own tests, simulator runs and PR:

- **Glasses app** (`glasses/`): the server HUD (#2), the manager HUD with role picker, exceptions and floor
  minimap (#3), the real-backend wiring (#8), the Vultr build target (#14), the three stacked Controls / Queue /
  Card tabs (#18), the 2-minute clip and the Verity processing animation (#22), ramp mode and head-nod accept
  (#30, nod HW-PENDING), blanking when idle (#32), the mic, draft screen and debug PCM path, and Sentry on the
  glasses (#20). It read the Even Hub SDK and simulator docs, proposed the glasses <-> backend message
  contract, and checked its work by driving the Even Hub simulator.
- **Voice relay** (`backend/voice/`): the ElevenLabs Scribe + agent spike (#1), live capture (#4), the
  rolling clip, "verity" voice commands, Controls menu and handoff (#9), the Gemini fallback for unknown
  command words (#15), the clip summary and menu-checked answers (#19), crowd-proof commands and diarized
  clips (#25), the clip leak-rate measurements (#29) and a test cleanup (#28), and the menu, order model and guards with their
  tests. It ran these live against ElevenLabs and measured latency and accuracy (`backend/voice/NOTES.md`).
- **Restaurant brain** (`backend/`, `data/`): the Python mirror of the contract, the mock server, the
  fictional menu and floor plan, the FastAPI/WebSocket hub with the task state machine (bounce, 30 s
  escalation, manager alert), the order-tool guards, the run-priority engine with its FIFO baseline and the
  kitchen "food up" endpoints (#6), course-wait, VIP-seated and 86 alerts (#23). A human set the rules (course
  above temperature, 5-minute ceiling, max 3 plates per runner, cold never delays hot).
- **Dinner-rush simulator** (`sim/`) and the run-planner work it drove: the simulator itself, FIFO vs
  priority on the real backend (#11), holding reserved servers for big courses (#13), the priority-vs-FIFO
  finding (#21), and mock servers next to the real G2 for the routing demo (#33).
- **Observability** (#17, #20): the Tiger Data event-log writer and schema (hypertable, continuous
  aggregates), Sentry for the backend (spans for dispatch, delivery, accept, done and food up), the pages
  (tracing, replay, DSN from `GET /config`) and the glasses, and the latency measurements in `backend/NOTES.md`.
- **Spoken floor requests and table statuses** (#34): "table 2 wants the check" from a clip or "verity ...",
  confirmed with a tap on the glasses, then routed by the backend; the backend and contract side included.
- **Docs and wrap-up:** the submission README (#31); a Devin session also tested and merged #35 and wrote
  this file's final version and the README's library list.

## What Claude Code built

- **Organizer and Kitchen web pages** (`web/`, #5, #7, #16): the shared backend client, the pure state reducer
  and its tests, the organizer floor plan and live dispatch board, the kitchen ticket rail with food-up
  buttons and allergy warnings, and the take-order button (#16). It checked the pages in headless Chrome
  (two tabs, timed), found a hub bug and reported it to the backend Devin session over the Devin API.
- **Vultr hosting** (`backend/deploy/`, #12): `provision.sh` (creates the server through the Vultr API),
  `deploy.sh`, `cloud-init.yaml` (first boot: Caddy, venvs, firewall, key-only SSH, service user), the Caddy
  site, and the `floor-sense-backend` / `floor-sense-voice` systemd units. It created the live server and
  checked it end to end. It also wrote the deploy fixes in #35 (building and shipping the Verity pages,
  creating both ElevenLabs agents on deploy).
- **Gemini task router and task rules** (`backend/app/router.py`, #10): Gemini picks the server, only the
  assigned server can accept, finish or bounce a task, task handoff and one-level revert, per-server task
  timing and rerouting tasks held too long. A human chose Gemini and reviewed the PR.
- **Verity pages** (`web/verity/`, #24, #26, #27): the React + Vite scroll story and the live manager
  dashboard, built from the team's Paper design, with the owner directing.
- **Driving Devin for Coder A's lane:** Claude Code wrote the prompts for the Devin sessions in Coder A's lane
  (`backend/`, `web/`, `sim/`), checked their PRs (ran the tests, reran the simulator, ran the secret scans)
  and merged them.

## How Gemini is used in the product

Both uses run on the backend with a server-side key (`GEMINI_API_KEY`) and the same model,
`gemini-3.1-flash-lite` (`FS_GEMINI_MODEL`). Gemini only proposes; code checks every answer.

- **Task routing.** When a task is created without a named server, `backend/app/router.py` sends Gemini the
  task, its table and every server's open tasks and timing stats, and Gemini answers with one server id (the
  answer is constrained to an enum of the real ids). If Gemini errors, takes longer than 3 s or has no key,
  the fixed rules pick the table's section server. Escalation and run priority are always plain code. Every
  pick is logged as `router.pick`.
- **Loose voice wording.** Only when the words right after "verity" are not a fixed command word (at most 5
  words), `backend/voice/gemini_intent.py` sends that short phrase, and nothing else, to Gemini (2 s
  timeout) to map it onto one of the same fixed actions, or onto a floor request or table status for one
  table. Code checks the action is on the list and the table exists; anything else shows
  `Didn't get: <words>` on the glasses.

## How ElevenLabs is used in the product

The glasses never call ElevenLabs and never hold the key: they stream G2 mic PCM (16 kHz) to the voice
relay (`backend/voice/relay.py`), which holds `ELEVENLABS_API_KEY`.

- **Order clips (Scribe batch + two agents).** The glasses keep the last 120 s of mic audio in memory only. A
  swipe back sends that clip to the relay, where **Scribe batch speech-to-text** (`scribe_v2`, English,
  diarized, biased with menu and staff keyterms) transcribes it in one call. Then two **ElevenLabs Agents in
  text-only mode** (LLM `claude-haiku-4-5`, chosen by a measured comparison in `backend/voice/NOTES.md`)
  read the transcript:
  - the **clip agent** returns the whole order by seat with one `set_order` tool call (dishes, alterations,
    allergies, notes, `?` lines), which code validates against `data/menu.json`;
  - the **talk agent** returns a short summary and answers to the guests' questions with one `set_talk` call;
    code checks every answer against the menu before it is shown.

  Floor requests in the clip ("table 2 wants the check") are spotted by plain code patterns, not an LLM.
  The agents never send or cancel anything: a tap on the glasses does. The relay keeps nothing of the audio
  or transcript after processing it.
- **Voice commands (Scribe realtime).** While the Server role is on, the live mic also streams to the relay,
  where **Scribe realtime speech-to-text** (`scribe_v2_realtime`, English, keyterm-biased) is used only to
  spot "verity" + a fixed command word (accept, done, clip, ...). Plain code matches the word list; the
  transcript is never logged, stored or forwarded.
- **Text to speech for tests only.** `make_fixtures.py` uses ElevenLabs TTS (`eleven_multilingual_v2`) to make
  test audio (orders, commands, noise mixes) in a gitignored folder. No real audio is recorded or stored.
