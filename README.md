# Floor Sense

Restaurant floor on Even Realities G2 glasses. See `AGENTS.md` for the brief.

## Frameworks and libraries

### Glasses app (`glasses/`)
- TypeScript (strict) + [Vite](https://vitejs.dev/): the Even Hub WebView app, scaffolded from
  [even-realities/evenhub-templates](https://github.com/even-realities/evenhub-templates) (`asr`)
- [@evenrealities/even_hub_sdk](https://www.npmjs.com/package/@evenrealities/even_hub_sdk) 0.0.16: G2 display, input and storage
- [@evenrealities/pretext](https://www.npmjs.com/package/@evenrealities/pretext): G2 font metrics for fitting card lines
- [@evenrealities/evenhub-simulator](https://www.npmjs.com/package/@evenrealities/evenhub-simulator) and
  [@evenrealities/evenhub-cli](https://www.npmjs.com/package/@evenrealities/evenhub-cli): simulator and `.ehpk` packing
- [vitest](https://vitest.dev/): tests
- [ws](https://www.npmjs.com/package/ws) and [tsx](https://www.npmjs.com/package/tsx): the dev-only fake backend

### Voice spike (`backend/voice/`)
- Python 3.11
- [httpx](https://pypi.org/project/httpx/): REST calls to ElevenLabs
- [websockets](https://pypi.org/project/websockets/): Scribe realtime and agent conversation sockets
- [python-dotenv](https://pypi.org/project/python-dotenv/): loads the local, gitignored root `.env`
- [pytest](https://pypi.org/project/pytest/): tests
- [ruff](https://pypi.org/project/ruff/): lint and format
- ElevenLabs APIs: Scribe realtime STT (`scribe_v2_realtime`), Agents (text-only mode, client
  tools), and text to speech for test fixtures

### Restaurant brain (`backend/`, `data/`)
- Python 3.11, type hints, [ruff](https://pypi.org/project/ruff/) and [pytest](https://pypi.org/project/pytest/)
- [FastAPI](https://fastapi.tiangolo.com/) + [uvicorn](https://www.uvicorn.org/): HTTP API and the WebSocket hub
- [pydantic](https://docs.pydantic.dev/) v2: Python mirror of `glasses/src/contract.ts`, every frame checked
- [websockets](https://pypi.org/project/websockets/): the step-0 mock server and the walkthrough client
- [httpx](https://pypi.org/project/httpx/): the walkthrough script and FastAPI's test client
- Shared fictional data in `data/menu.json` and `data/floor.json`; message contract in `backend/CONTRACT.md`

### Web pages (`web/`)
- Plain HTML, CSS and JavaScript ES modules, no framework or build step
- Node's built-in test runner (`node --test`): tests for the page state
- [playwright-core](https://www.npmjs.com/package/playwright-core) with the local Chrome: used
  during development to check the pages in two tabs; not a dependency of the repo
