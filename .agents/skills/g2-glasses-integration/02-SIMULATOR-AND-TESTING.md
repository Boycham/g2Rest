# 02. Simulator and testing

## The simulator

- Run `evenhub-simulator` with its **automation port** so you can work without a person:
  - `GET /api/screenshot/glasses`: screenshot of what the glasses show
  - `POST /api/input`: send tap, double tap, long press, swipe up, swipe down (simulator names; up = a forward swipe on the G2)
  - `GET /api/console`: read the app's console
  No `evenhub login` is needed. Check the simulator's `--help` for the current flags.
- It uses the laptop mic (`--list-audio-input-devices`, pick one with `--aid`). In a cloud VM there may be no mic
  at all, so build the text-injection and PCM-file paths first.
- It supports tap, double tap, swipes and the mic. It sends long press too (0.9.5). It does **not** support
  ring source, device status, IMU, real fonts, or the exit dialog (`shutDownPageContainer(1)` just blanks the
  display).
- **Restart the simulator after every app or backend restart.** Otherwise it keeps showing cards but silently
  stops delivering gestures, or stops reconnecting.
- Its console is a ring buffer flooded by audio frames and keeps old entries: only read entries newer than the
  start of your run.

## Debug paths to build early

- **Inject text** into a live order session (skips speech-to-text, still exercises the agent and the cards).
- **Stream a PCM file** in real-time 100 ms chunks through the real pipeline. Generate test audio with ElevenLabs
  text-to-speech (PCM 16 kHz output) into a gitignored `fixtures/` folder. Never commit audio.
- **Reset state** (orders, queue, cooldowns) before each end-to-end run, or the first event gets swallowed.
- Protect debug routes with their own token if the backend is public.

## Testing rules

- Don't call anything done until you've seen it work: a passing test, a simulator screenshot attached to the
  PR, or a run log with numbers.
- Unit-test the rules (menu guard, alteration guard, confirm/cancel needs a tap, card text limits, task state
  machine) without calling ElevenLabs or the simulator.
- **One success is not a test.** Run agent and voice flows several times (at least 5) and report the median.
- Wait for the backend's health endpoint before running end-to-end tests.
- Mute or skip the mic in scripted tests (room noise resets timers).
- Put measured numbers in `NOTES.md` and in commit bodies for perf changes.

## HW-PENDING: checks a person runs on a real G2

Write each answer in `NOTES.md` when someone reports it. Ask for these in your PR if they block your work.

1. The app starts, connects to the backend, and mic frames arrive.
2. A task card appears within about 1 s of the backend sending it, fits at the real font, and wraps correctly.
3. Is `rebuildPageContainer` flicker acceptable when switching screens?
4. Tap arrives as a click: accept, then done.
5. Swipe back arrives as scroll bottom and clips the last minute; swipe forward (scroll top) opens Controls; long press opens the handoff popup.
6. Double tap shows the real system exit dialog.
7. Lock the phone for 5 minutes: does the socket reconnect, and does the queue come back?
8. Speak an order in a noisy room: how much of it does speech-to-text get?
9. Does saved state survive an app restart?
10. Does any gesture arrive from the R1 ring, and does the firmware reserve any gesture?
