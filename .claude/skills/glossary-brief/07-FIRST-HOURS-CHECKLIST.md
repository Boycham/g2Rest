# 07. First hours checklist

Times are from the moment hacking starts (T+0). The goal for the first 6 hours is a real card on a real G2,
installed as a Beta build. Everything else waits for that.

## Before leaving for the event

- [ ] Accounts ready and logged in: Even Hub developer (`evenhub login` done), Gemini (AI Studio key), Deepgram,
      Sentry, ElevenLabs (if trying Scribe), Paper Pro with `LAHACKS26` (if entering Paper), Tailscale (if using Funnel).
- [ ] Node 24, npm, the Even CLI and simulator, Even's Claude Code plugin skills, Sentry and Paper plugins installed.
- [ ] Phone has the Even Realities app (version ≥ the SDK's minimum app version).
- [ ] Rotate any key that was ever pasted into a chat.
- [ ] Laptop charger, phone hotspot working, headphones.

## T+0:00 – T+0:30 · Check-in and decisions

- [ ] One person goes **straight to the Even Realities table**: borrow a G2, pair it to a team phone, confirm
      the Beta tester area now appears in the phone app.
- [ ] Ask an organizer about rule 2 (see [03](03-RULES-AND-INTEGRITY.md)); get the answer in writing. Confirm the
      submission deadline and whether Devpost limits tracks per project.
- [ ] Confirm the ElevenLabs credit amount (only matters if Scribe is tried).
- [ ] Assign owners: glasses app, server, companion + agent, design (Paper only if someone owns it).
- [ ] Create the **new empty repo**. First commit: README stub, `.gitignore` (env files, `.ehpk`, `dist/`, data,
      audio), `.env.example` files.

## T+0:30 – T+1:30 · Hello world on real glasses (pass/fail gate)

- [ ] Scaffold the glasses app from Even's `asr` template; upgrade the SDK; set `min_app_version`.
- [ ] Hello-world text on the simulator.
- [ ] Pack an `.ehpk`, upload on hub.evenrealities.com → Builds → Beta group with your email → install on the
      paired phone → launch on the G2. Note how long each step takes.
- [ ] Fallback if Beta is slow: Developer Mode private build to keep testing; keep retrying Beta in parallel.

## T+1:30 – T+3:00 · Stable host and audio

- [ ] Server skeleton with a health endpoint, the glasses WebSocket, and Sentry (tracing + logs) from the start.
- [ ] Stable public host (Tailscale Funnel or a VPS). Put its `https://` and `wss://` in the `app.json` whitelist.
      Token on the API and sockets; separate token on debug routes.
- [ ] Mic → server → Deepgram (behind the speech-to-text interface) → transcript line on the glasses.
- [ ] **On the real G2:** does the app connect, does audio stream, how loud is the wearer vs a person 1 m away?

## T+3:00 – T+6:00 · Core loop on the G2

- [ ] Hand-written seed list of 5 terms (the agent comes later).
- [ ] Matcher (aliases, inflections), card rules (one card, 30 s, 2 min, confidence, 15 s fade), card display.
- [ ] Gestures: tap dismiss (twice = learned), swipe up re-show, swipe down marker, double tap exit.
- [ ] Learned ids in SDK storage.
- [ ] Debug routes: inject text into the live session; reset state; (later) stream a WAV file.
- [ ] Run the HW-PENDING list below on the G2 and write down each answer.
- [ ] Commit after each working piece.

## HW-PENDING checks on the borrowed G2 (in order)

1. App starts, connects to the server, mic frames arrive.
2. Someone says a term near the glasses: card within ~2 s, fits the lines at the real font, wraps correctly.
3. Is the card show/hide flicker acceptable?
4. Single tap arrives as a click and dismisses; two dismissals mark learned.
5. Swipe down arrives as scroll-bottom; the recap appears after ~20 s of quiet.
6. Double tap shows the real system exit dialog.
7. Lock the phone for 5 minutes: does the socket reconnect and the mic re-enable on foreground?
8. Is the wearer's voice loud enough relative to others for loudness-based wearer detection?
9. Do learned terms survive an app restart?
10. Does any gesture arrive from the ring, and does the firmware reserve any gesture?

## After T+6:00 · Order of the rest

1. "Used correctly?" auto-learn and wearer calibration.
2. "I'm lost" recap.
3. Companion Review screen + the jargon-pack agent + the fictional company docs (can start in parallel from T+1:30
   with a separate owner).
4. Learned screen with "Wrong?".
5. Sentry Session Replay on the companion, AI agent monitoring, distributed trace click → server → storage.
6. Recorded-audio demo mode (WAV through the real pipeline, triggered from a hidden companion control).
7. Paper designs and polish (if entered), README with G2 install steps, demo video, Devpost.
8. Crowd-noise test: play a crowd recording under the recorded demo sentences and count terms caught (and
   wrong cards) with exact matching, + aliases, + sound-alike matching, for Deepgram and, if it's being
   considered, ElevenLabs Scribe. Keep the winner and quote the numbers in the Sentry and Gemini write-ups.

Code freeze and video recording happen **before** the deadline, not at it.
