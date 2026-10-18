# AI usage

## How AI built this

- **Devin (Cognition)** wrote the glasses server HUD in `glasses/`: it read the Even Hub SDK and simulator
  docs, proposed the glasses <-> backend message contract, wrote the card formatter, task state machine,
  socket and storage code, the fake backend used for development, and the tests, and drove the Even Hub
  simulator to check it. A human briefed and reviewed the work.
- **Devin (Cognition)** wrote the voice spike in `backend/voice/`: it read the ElevenLabs docs,
  wrote the menu, the order model and guards, the tests, the ElevenLabs session code and the CLI
  scripts, and ran them live against ElevenLabs. A human briefed and reviewed the work.
- **Claude Code (Anthropic, Claude Opus 5.5)** wrote the organizer and kitchen web pages in `web/`:
  it read the backend-core branch and the glasses contract, wrote the pages, the state reducer and
  its tests, checked the pages in headless Chrome (two tabs, timed), and found and reported a hub
  bug and a missing allergy warning on kitchen tickets. It also coordinated the backend-core Devin
  session over the Devin API. A human directed and reviewed the work.

## How ElevenLabs is used in the product

- **Scribe realtime speech-to-text** turns the server's spoken order (G2 mic, 16 kHz PCM) into
  transcript segments.
- An **ElevenLabs Agent in text-only mode** turns each committed segment into tool calls
  (add/remove/modify item, set allergy, propose confirm/cancel). Our code validates every call
  against the menu. The agent can only propose sending or cancelling an order; a tap on the
  glasses does it.
- **ElevenLabs text to speech** generates test audio for development only. No real audio is
  recorded or stored.
- The server HUD in `glasses/` doesn't call ElevenLabs.
