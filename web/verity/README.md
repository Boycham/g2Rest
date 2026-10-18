# Verity web: scroll story + manager dashboard

Two pages built from the Paper file "Verity Blockborn Page (copy)" (the Roblox-style version):

- `index.html`: the scroll story. Five scenes (Welcome, Tasks, Voice, Inside, Floor) driven by the
  Developer Handoff keyframes; scrolling steps from one keyframe "page" to the next.
- `dashboard.html`: the live manager dashboard (Paper pages 08 and 09). It replaces the Organizer
  page for managers; `web/index.html` stays as the fallback (it still has Reset service).

React 18 + Vite, GSAP (ScrollTrigger, SplitText, Flip), Lenis (smooth scroll + snap), and five
React Bits components (`src/components/reactbits/README.md`).

## Run it

```sh
# backend (empty FS_TOKEN = open dev mode)
cd backend && FS_TOKEN= .venv/bin/uvicorn app.main:app --port 8787

# Verity pages
cd web/verity && npm ci && npm run dev        # http://localhost:5176/ and /dashboard.html
```

Point at another backend with `?api=https://host&token=...` (same as the other pages; the token
moves to sessionStorage and leaves the address bar). Built (`npm run build`), the pages land in
`web/verity/dist/`, next to the existing pages, so `/app/verity/dist/dashboard.html` on the server.
The Kitchen links go to `web/kitchen.html`; in dev set `VITE_WEB_URL` if `web/` isn't served on
`http://localhost:5173/`. The shift clock reads `?shiftEnd=HH:MM`; without it, it counts to the next service end (lunch 15:00,
dinner 22:00).

Checks: `npm run build` (TypeScript, then Vite) and `npm test` (Node's runner: the keyframe math
and the dashboard view model).

## The scroll story

- One fixed viewport; a 1000vh page under it. ScrollTrigger turns the scroll position into
  progress 0..1, split per the handoff: S01 0–20%, S02 20–40%, S03 40–60%, S04 60–85%,
  S05 85–100%. Lenis smooths with lerp 0.12 (the handoff's smoothing) and Lenis Snap settles on
  the nearest keyframe of any scene, so each flick moves one "page". Arrow keys and Page Up/Down
  step one keyframe; the dots on the right jump to where a scene is fully built (`BUILT` in
  keyframes.js: KF0, KF25, KF75, KF75, KF100).
- `src/site/keyframes.js` holds every layer's keyframes and the camera rule
  P' = (720,450) + s·(P − c). Each layer moves as translate + scale (scale = width ÷ KF0 width,
  origin 0 0). Two layers per scene: photos, doors and pins fill the window; copy and cards fit
  inside it (a 430×900 stage on phones in portrait).
- Discrete states (the task card NEW → ACCEPTED → DONE, the voice panel READY → LISTENING →
  STRUCTURING → CONFIRM → SENT, cue text) swap at the midpoint between keyframes with a 150ms
  crossfade. Scenes crossfade into each other at their boundaries.
- Reduced motion: no smoothing, snap or crossfade; each scene holds the same fully built
  keyframe the dots land on.

## The dashboard

- Data: `GET /floor` once, `GET /state` on every (re)connect, the organizer socket through the
  shared reducer (`../state.js`, `../client.js`), `GET /events` for routing history (pulled after
  each task frame and every 3 s), `GET /stats` every 5 s, `GET /health` every 4 s.
- Board columns: Unassigned (the holder's glasses are offline, so the card is queued), Waiting for
  accept (most urgent first, with a ring that drains over the backend's escalation window from
  `/stats.escalationSec`), Accepted, Done. Card states follow the event log: escalated (over the
  limit or passed on), bounced / handed off (dashed), rerouted, reverted. When a task changes
  state its card flies to the new column (GSAP Flip).
- Alerts rail: every alert the backend sends, whatever its kind, from its payload (level → colour,
  text as sent, `table` → Open table). Alerts tied to a task (found through `alert.raised` in the
  event log, or the task id in the alert id) get "Reroute to …". Diner questions the menu
  couldn't answer (`order.draft` answers with `known: false`, and `uncertain`) show as "?" items
  and a "?" badge on the table. Dismiss hides an item on this screen only.
- Reroute is `POST /tasks/{id}/reroute {to}` (new). The suggestion is the online server with the
  fewest open tasks other than the holder; `to: null` lets the backend's router pick.
- Drawers: Staff (glasses online, open tasks, done count and average from `/stats`), Routing log
  (every assignment, accept, bounce, escalation and finish, with the reason), Table details
  (state, time in status, the current task with Reroute, the latest clip summary and suggested
  answers, orders, table status buttons, other tasks there).
- Backend lost: the chip turns red, dispatch pauses at 50%, and a banner over the floor offers
  "Retry now" with the countdown to the next automatic try.
- Sentry: same pinned CDN script and `startSentry` / `traced` as the other pages; the DSN comes
  from `GET /config`.
- Below 1024px wide the page shows a notice instead (the design is 1440×900, tablet 1024×768).

## Backend additions (in this PR)

- `POST /tasks/{id}/reroute {to?}`: the manager moves an open task. Logged as
  `manager reroute to <id>`; the old holder's "verity revert" can't undo it.
- `GET /health` adds `online`: staff whose glasses are connected.
- `GET /stats` adds `escalationSec`.
