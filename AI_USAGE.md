# AI usage

## How AI built this

- **Devin (Cognition)** wrote the glasses server HUD in `glasses/`: it read the Even Hub SDK and simulator
  docs, proposed the glasses <-> backend message contract, wrote the card formatter, task state machine,
  socket and storage code, the fake backend used for development, and the tests, and drove the Even Hub
  simulator to check it. A human briefed and reviewed the work.

## How ElevenLabs is used in the product

- Not used by the server HUD yet. Voice order capture is built in a separate session.
