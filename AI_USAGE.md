# AI usage

## How AI built this

- **Devin (Cognition)** wrote the glasses server HUD in `glasses/`: it read the Even Hub SDK and simulator
  docs, proposed the glasses <-> backend message contract, wrote the card formatter, task state machine,
  socket and storage code, the fake backend used for development, and the tests, and drove the Even Hub
  simulator to check it. A human briefed and reviewed the work.
- **Devin** also wrote the manager HUD in `glasses/` (role picker, exceptions list, floor minimap): it chose
  the container layout from the SDK types, proposed the `alert` / `floor.state` field additions, extended
  the fake backend with a manager script, wrote the tests, and checked it in the Even Hub simulator. A
  human briefed and reviews the work.
- **Devin (Cognition)** wrote the voice spike in `backend/voice/`: it read the ElevenLabs docs,
  wrote the menu, the order model and guards, the tests, the ElevenLabs session code and the CLI
  scripts, and ran them live against ElevenLabs. A human briefed and reviewed the work.
- **Devin (Cognition)** wrote the restaurant brain in `backend/` (not `backend/voice/`) and the shared
  data in `data/`: the Python mirror of the message contract and the mock WebSocket server, the fictional
  menu and floor plan, the FastAPI/WebSocket hub with the task state machine (bounce, 30 s escalation,
  manager alert), the order-tool guards, the run-priority engine with its FIFO baseline, the kitchen
  "food up" endpoints, the tests and the walkthrough script. A human briefed it, set the rules
  (course above temperature, 5-minute ceiling, max 3 plates per runner, cold never delays hot) and
  reviewed the PR; the web lane's requests (pass endpoints) came through the same session.
- **Claude Code (Anthropic, Claude Opus 5.5)** wrote the organizer and kitchen web pages in `web/`:
  it read the backend-core branch and the glasses contract, wrote the pages, the state reducer and
  its tests, and checked the pages in headless Chrome (two tabs, timed). Along the way it added an
  allergy warning to kitchen tickets and found a hub bug, which it reported to the backend-core
  Devin session; it relayed the web lane's requests to that session over the Devin API. A human
  directed and reviewed the work.
- **Claude Code** also wrote the Gemini task router (`backend/app/router.py`) and its tests, and made
  task accept/done/bounce the assigned server's action only. A human chose Gemini and reviewed the PR.

## How Gemini is used in the product

- **Task routing.** When a task is created without a named server, `backend/app/router.py` sends Gemini
  the task, its table and every server's open tasks, and Gemini answers with one server id (the
  answer is constrained to the real ids). If Gemini errors, takes longer than 1.5 s or has no key,
  the fixed rules pick the table's section server. Every pick is logged as `router.pick`.

## How ElevenLabs is used in the product

- **Scribe realtime speech-to-text** turns the server's spoken order (G2 mic, 16 kHz PCM) into
  transcript segments.
- An **ElevenLabs Agent in text-only mode** turns each committed segment into tool calls
  (add/remove/modify item, set allergy, propose confirm/cancel). Our code validates every call
  against the menu. The agent can only propose sending or cancelling an order; a tap on the
  glasses does it.
- **ElevenLabs text to speech** generates test audio for development only. No real audio is
  recorded or stored.
- The glasses never call ElevenLabs and never hold the key: they stream G2 mic PCM to the voice
  relay (`backend/voice/relay.py`), which talks to Scribe and the agent and sends back the draft.
- Devin also wrote the voice relay, the order proposal guards, and the glasses' mic, draft screen
  and debug PCM path, and tested them in the simulator. A human briefed and reviewed the work.
