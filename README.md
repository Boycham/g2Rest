# Floor Sense

Restaurant floor on Even Realities G2 glasses. See `AGENTS.md` for the brief.

## Frameworks and libraries

### Voice spike (`backend/voice/`)
- Python 3.11
- [httpx](https://pypi.org/project/httpx/): REST calls to ElevenLabs
- [websockets](https://pypi.org/project/websockets/): Scribe realtime and agent conversation sockets
- [pytest](https://pypi.org/project/pytest/): tests
- [ruff](https://pypi.org/project/ruff/): lint and format
- ElevenLabs APIs: Scribe realtime STT (`scribe_v2_realtime`), Agents (text-only mode, client
  tools), and text to speech for test fixtures
