# 04. Glasses ↔ backend architecture

## Shape

```
[G2 glasses] <-Bluetooth-> [Even Realities phone app, hosting our WebView app (glasses/)]
                                   |
                 WebSocket: mic PCM up; task cards, order state, HUD data down
                                   |
              [Backend: Python FastAPI (Coder A), voice module backend/voice/ (Coder B)]
                                   |
                     [Organizer, kitchen and dashboard web pages (web/)]
```

- The glasses and backend talk through a **frozen message contract**. Don't change it alone; propose changes
  in your PR. Until the real backend exists, work against Coder A's stand-in backend that sends fake messages.
- The glasses app holds no business logic: the backend decides tasks, priority and order state; the glasses
  render it and send gestures and audio.

## Secrets

- API keys stay on the backend. Even's `asr` template puts the speech key in the WebView bundle; don't. Stream
  audio to our backend instead.
- A shared token on the API and sockets keeps strangers out (it ships in the bundle, so it's not real auth).
  Debug routes get a separate token, and debug mode is off on a public host unless those routes are protected.

## Session lifecycle

- One session per glasses connection. Reconnect with backoff; on the foreground event, reconnect and re-sync
  state from the backend (the backend is the source of truth; SDK storage is a cache for instant redraw).
- On backend start, close sessions left open by a crash.
- If the voice stream drops mid-order, reopen it with backoff and keep the partial order.

## Hosting

The packed app's `app.json` must whitelist the backend's exact `https://` and `wss://` host **at pack time**,
so the host must be stable before the Beta build.

- **A small VPS (e.g. Vultr) with Caddy** for automatic TLS. `<ip-with-dashes>.sslip.io` gives a hostname
  without buying a domain.
- **Tailscale Funnel** from a laptop worked before: a fixed `https://<machine>.<tailnet>.ts.net` URL that
  survives restarts, 5 minutes of 16 kHz audio with no lost frames, p95 latency about 22 ms, also over a phone
  hotspot. The laptop must stay awake and online.
- **Not** Cloudflare quick tunnels: the URL changes every run, which forces a repack and re-upload.
- Venue Wi-Fi may isolate devices or have a sign-in page. Route everything through the cloud backend and keep
  a phone hotspot ready.

Creating cloud servers or buying a domain needs a person's OK.
