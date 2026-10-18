# 01. G2 SDK and Even Hub

## Getting started

- **Scaffold** with `npx degit even-realities/evenhub-templates/asr glasses`. The template's speech-to-text file
  is a stub that throws; it has no vendor code. It also puts the speech key in the WebView bundle; don't do
  that (see [04](04-ARCHITECTURE.md)).
- **SDK version:** `@evenrealities/even_hub_sdk` 0.0.16 was the latest when tested; `zOrderIndex` and image LZ4
  need 0.0.12+. The template pinned 0.0.10, and for 0.0.x a caret range (`^0.0.10`) means exactly 0.0.10, so
  upgrade explicitly. After an SDK upgrade, restart Vite with `--force` or it keeps serving the old cached SDK.
- **Even's own agent skills** exist in the `everything-evenhub` plugin (glasses-ui, handle-input,
  device-features, font-measurement, test-with-simulator, build-and-deploy, sdk-reference). If they're
  available to you, read them; otherwise use hub.evenrealities.com and the SDK's type definitions.
- **Read Even's testing and shipping docs** (hub.evenrealities.com) before choosing gestures or behaviour. That
  is where the auto-reject rules live.

## Display

- 576×288 per eye, monochrome green, 5 brightness levels. Use brightness for urgency (the brightest item is the
  one that needs attention), never as the only signal.
- With 27 px lines, a 1 px border and 6 px padding, a full-width card's inner width is 562 px: about 63
  characters per line of average English (worst case about 40 with wide letters). Measure at runtime with
  Even's text-measurement package (`@evenrealities/pretext`) instead of counting characters.
- Three text lines need a box about 96 px tall.
- No gesture hints on the display. Explain gestures on the phone screen and in the README.
- Blank when nothing needs the wearer. Even judges "Quiet by Design".

## Input

- Event types: `CLICK_EVENT`, `SCROLL_TOP_EVENT` (swipe fwd), `SCROLL_BOTTOM_EVENT` (swipe back), `DOUBLE_CLICK_EVENT`, long press (`LONG_PRESS_EVENT = 9`, release = 10, in
  SDK 0.0.16), lifecycle, IMU.
- On the G2 touchpad `SCROLL_TOP_EVENT` is a swipe **fwd** (toward the eyes) and `SCROLL_BOTTOM_EVENT` a swipe **back** (toward
  the ear), checked on a real G2 at 0.1.5. Wearer-facing text says fwd/back, never up/down.
- Tap arrives as a sys event with `eventType` undefined (that means click). Double tap arrives as type 3.
- Swipes arrive as text events (`SCROLL_TOP_EVENT` / `SCROLL_BOTTOM_EVENT`) on the event-capture container **with no event
  source**, so ring and temple swipes can't be told apart.
- **Only one container per page captures input.** Design each page around that.
- **Root-page double tap must call `shutDownPageContainer(1)`.** `0` or a custom exit screen gets the app
  auto-rejected.
- IMU gives raw x/y/z only. Head gestures (nod) are out of scope for Floor Sense: accept is a tap or "verity accept".
- Floor Sense mapping (`glasses/src/controls.ts`): three stacked tabs, top to bottom Controls, Queue, Card (home).
  Swipe fwd = one tab up, swipe back = one tab down; on the Card tap = accept, tap again = done, swipe back = clip
  the last 2 minutes as an order, long press = handoff popup; long press elsewhere = back to the Card; double tap = exit.
- Even's docs don't describe the system dashboard's tab look. The rail follows their documented patterns: text
  containers stacked at 96 px, the open one bordered (`borderWidth`) and brighter, only the content captures input.

## Rendering

- `createStartUpPageContainer`: call **exactly once** per app run.
- `textContainerUpgrade`: update a text container in place, about 2 ms, no flicker. Use it for every card change.
- `rebuildPageContainer`: 1–6 ms on the simulator, but Even's docs warn it can flicker on hardware
  (HW-PENDING). Use it only to switch screens (server card ↔ order capture ↔ queue, manager HUD ↔ minimap).

## Audio

- The mic streams PCM 16 kHz, signed 16-bit little-endian, mono, in 3200-byte frames (100 ms).
- The G2 has **no speaker**. Nothing can get the wearer's attention without them looking up.
- Turn the mic on only while an order is being taken (privacy, and Even and judges will ask).

## Storage and lifecycle

- When the Even phone app goes to the background, it reloads the plugin in a hidden WebView and restores only
  the state you saved. If you skip that, the server's queue resets.
- Browser `localStorage` does not reliably survive restarts inside the Even app. Use SDK storage
  (`bridge.setLocalStorage` / `getLocalStorage`). Persistence across a real app restart is HW-PENDING.
- On the foreground lifecycle event: reconnect the socket and re-enable the mic if an order was in progress.
- Even asks for a **5-minute locked-phone test** before submission.

## Network

- Calls only work to hosts in the `app.json` network permission: list the `https://` and `wss://` form of
  exactly the hosts you call. `pack` rejects an empty whitelist. CORS still applies on top.
- WebSocket support inside the Even app was not confirmed in the docs. Check it early; keep server-sent events
  as a fallback.

## Logs

- The SDK logs every event, including each audio frame's full PCM bytes, ten times a second. Prefix your own
  lines (`[fs]`) and filter by the prefix.
- On Beta builds, console logs show in the phone app's Developer Mode console. Don't log secrets. Crashes are
  not auto-reported.

## Packing and shipping

- Pack: `npx evenhub pack app.json dist -o floor-sense.ehpk --sdk-ver <sdk>`. Pack raises `min_app_version` to
  the SDK's floor (0.0.16 → Even app 2.2.10); set it in `app.json` to match. `pack -c` prints nothing either
  way, so it tells you nothing. Beta installs fail if `min_sdk_version` is above the tester's firmware.
- App name: at most 20 characters, must not contain "Even". "Floor Sense" is fine.
- No medical, financial or emergency-routing features (banned on Even Hub).
- **The CLI has no upload command** (only login, init, pack, qr), and `evenhub login` is interactive. Upload is
  manual and done by a person: hub.evenrealities.com → project → Builds → upload → push to a Beta group with
  their email → phone: Even Realities app → Me → Beta tester → Install → launch from the glasses home screen.
- The phone app hides Beta tester / Even Hub until glasses are paired. Developer Mode private builds are the
  faster loop for smoke tests; Beta is the path judges need.
- Never commit `*.ehpk` or `dist/`.
