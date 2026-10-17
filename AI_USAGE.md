# AI usage

## How AI built this

- **Devin (Cognition)** wrote the voice spike in `backend/voice/`: it read the ElevenLabs docs,
  wrote the menu, the order model and guards, the tests, the ElevenLabs session code and the CLI
  scripts. A human briefed and reviewed the work.

## How ElevenLabs is used in the product

- **Scribe realtime speech-to-text** turns the server's spoken order (G2 mic, 16 kHz PCM) into
  transcript segments.
- An **ElevenLabs Agent in text-only mode** turns each committed segment into tool calls
  (add/remove/modify item, set allergy, propose confirm/cancel). Our code validates every call
  against the menu. The agent can only propose sending or cancelling an order; a tap on the
  glasses does it.
- **ElevenLabs text to speech** generates test audio for development only. No real audio is
  recorded or stored.
