# Floor Sense: G2 glasses app

The Even Hub app for Even Realities G2 glasses. It shows the restaurant floor on the glasses and stays blank
when nothing needs the wearer. Pick the role on the phone screen with the Server / Manager select. The role is
saved in SDK storage, and Server is the default.

- **Server:** one task card at a time (`RUN · T12 · 2× halibut s1+3`), allergies on the top line, and
  `+N queued` in the corner.
- **Manager:** a list of exceptions only, most urgent first (`! T4 waiting 14m on mains`, `T3 task unacked 60s`).
  Timers tick on the glasses. Swipe down for a minimap of 8 tables: each box shows a status glyph and minutes,
  and the brightest box is the one that needs you.

The glasses talk to the backend over one WebSocket using the message contract in `src/contract.ts`. The URL
comes from `VITE_BACKEND_URL` in the root `.env` (see the root `.env.example`) and defaults to
`ws://localhost:8787/ws`.

## Run against the fake backend and the simulator

```sh
cd glasses && npm install
npx tsx dev/fake-backend.ts          # FAKE backend: ws://localhost:8787/ws, state page http://localhost:8787/
npx vite                             # app on http://localhost:5173
npx evenhub-simulator http://localhost:5173 --automation-port 9898   # restart after every app/backend restart
npm test && npm run build
```

The fake backend replays a server task script and loops a 60 s manager script: 8 tables, T4 goes late, and
alerts appear and clear. `POST /late?table=T2` makes any table late, and `POST /reset` starts over. On Linux,
if `npx evenhub-simulator` can't find the package or won't start, see the setup notes in [NOTES.md](NOTES.md).

On real glasses: `npx evenhub qr --url http://<your-ip>:5173`. To pack: `npm run pack` (writes
`floor-sense.ehpk`; add the real backend host to `app.json` first). For the Vultr host:
`VITE_FS_TOKEN=<server FS_TOKEN> npm run pack:vultr` (upload steps in [NOTES.md](NOTES.md)).

## Gestures

| Gesture | Server | Manager |
|---|---|---|
| Tap | accept the task; tap again when it's done | dismiss the top exception (on this device only); on the minimap, back to exceptions |
| Swipe up | queue (swipe up or tap to go back) | back to exceptions from the minimap |
| Swipe down | take an order; swipe down again to stop | floor minimap |
| Double tap | exit (`shutDownPageContainer(1)`) | exit (`shutDownPageContainer(1)`) |

Minimap glyphs: `!` needs you, `S` seated, `O` ordered, `W` waiting on food, `E` eating (mains out),
`C` check, `-` empty.

## More

[NOTES.md](NOTES.md) has what was checked in the simulator, the surprises, what's not done yet and the
`HW-PENDING` list for real hardware. The SDK and simulator details are in
`.agents/skills/g2-glasses-integration/`.
