---
name: g2-glasses-integration
description: How to build, test and ship the Floor Sense Even Realities G2 glasses app (TypeScript + Vite + Even Hub SDK) and its ElevenLabs voice path. Use before writing or changing anything in glasses/ or backend/voice/, and whenever a question comes up about G2 gestures, the 576x288 display, mic audio, the evenhub simulator, packing an .ehpk, Even Hub Beta builds and review rules, app lifecycle and storage, or what still needs checking on real hardware.
---

# G2 glasses integration (Floor Sense)

Everything we already know about building on Even Realities G2, written down so you don't relearn it the hard
way. It holds facts, gotchas and procedures, not code. The product itself (server cards, voice orders, manager
HUD, run priority) is described in `AGENTS.md` at the repo root; read that first.

## Read this first

- **Facts here were true when tested on the simulator** before the event. SDK versions, model IDs and API shapes
  change: check the current docs (hub.evenrealities.com, the SDK's npm page, elevenlabs.io/docs) before relying
  on one, and write what you confirmed in your lane's `NOTES.md`.
- **Nothing here has been proven on a real G2.** Items marked **HW-PENDING** must be checked on the glasses; a
  person has to do that (see [02-SIMULATOR-AND-TESTING.md](02-SIMULATOR-AND-TESTING.md)).
- **Lessons are past observations, not limits.** If something here doesn't match what you see now, trust what
  you see, and note the difference in `NOTES.md`.
- **Write all code fresh in this repo.** This skill contains no code on purpose (event rule: all work is done at
  the event). Public SDKs, Even's templates and npm/PyPI packages are fine.

## Files

Read the file for the area you're about to touch before designing or changing it.

| File | Read it before | It prevents |
|---|---|---|
| [01-SDK-AND-EVEN-HUB.md](01-SDK-AND-EVEN-HUB.md) | Any glasses code: display, gestures, rendering, audio, storage, lifecycle, network, packing | An app Even's review auto-rejects; flicker; a queue that resets when the phone locks |
| [02-SIMULATOR-AND-TESTING.md](02-SIMULATOR-AND-TESTING.md) | Running or testing the glasses app; calling something done | Silent gesture loss after restarts; untested "done"; missed hardware checks |
| [03-VOICE.md](03-VOICE.md) | Mic streaming, ElevenLabs speech-to-text, the order agent and its tools | Lost last words; an agent that applies things it shouldn't; crashes on bad tool calls |
| [04-ARCHITECTURE.md](04-ARCHITECTURE.md) | Connecting the glasses to the backend; hosting; secrets | Keys in the WebView; a host URL that changes after packing; a dead socket after background |
| [05-RISKS-AND-PROCESS.md](05-RISKS-AND-PROCESS.md) | Planning a task, or when something fails in a way that feels familiar | Repeating mistakes we already paid for |

## The rules that matter most

1. **Double tap on the root page always calls `shutDownPageContainer(1)`** (the system exit dialog). Anything
   else gets the app auto-rejected. Never use double tap for anything else.
2. **Long press exists** (SDK 0.0.16 `LONG_PRESS_EVENT = 9`). Swipes run fwd (toward the eyes, SDK `up`) and
   back (toward the ear, SDK `down`) on a real G2. Our gestures: tap = accept, tap again = done; swipe back = clip the
   last 2 minutes as an order (on the Card); swipe fwd = one tab up (Card → Queue → Controls); long press = handoff
   on the Card, back to the Card elsewhere; double tap = exit.
3. **Update cards in place with `textContainerUpgrade`.** Use `rebuildPageContainer` only to switch screens.
4. **API keys never go in the glasses bundle.** The WebView ships to every phone. Audio goes to our backend,
   which holds `ELEVENLABS_API_KEY`.
5. **Every host the app calls is listed in `app.json`**, and that host must be stable before packing.
6. **Save state with SDK storage, not `localStorage`**, and reconnect on the foreground event.
7. **Build a debug path that skips the mic** (inject text, stream a PCM file). The simulator mic is unreliable
   and judges' halls are loud.

## When a step needs a person

Even Hub login and upload, installing a Beta build on a phone, pairing glasses, recording audio, and creating
accounts all need a human. Stop, write numbered steps with exact commands, and wait. Don't try to work around it.
