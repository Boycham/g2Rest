# Hosting on Vultr

One small Vultr server runs the whole restaurant brain, so the real G2 can reach it from any network
(venue Wi-Fi isolates devices, and the phone can stay on cellular).

```
phone / glasses / browser --https, wss--> Caddy :443 (<ip>.sslip.io, Let's Encrypt)
                                            |-- /app/*  -> web/ (Organizer, Kitchen)
                                            `-- else    -> backend 127.0.0.1:8787 (FastAPI, /ws hub)
                                                              `-- voice relay localhost:8790 -> ElevenLabs
```

- **Server:** Vultr `vc2-1c-2gb` (1 vCPU, 2 GB) in Los Angeles (`lax`), Ubuntu 24.04, about $10 a month
  billed hourly. First boot (`cloud-init.yaml`): Caddy, Python venvs, `ufw` with only 22, 80 and 443
  open, key-only SSH, and a `floorsense` service user.
- **Name and TLS:** no domain yet, so the host is `<ip-with-dashes>.sslip.io`, which resolves to the IP;
  Caddy gets a real certificate for it. Swap in a GoDaddy domain later by changing the Caddyfile host.
- **Services:** `floor-sense-backend` (uvicorn) and `floor-sense-voice` (`relay.py`), both systemd,
  restart on failure, with separate venvs because they pin different `websockets` versions.
- **Secrets:** only in `/etc/floor-sense/env` on the server (root and `floorsense` only). `deploy.sh
  --env` writes it over SSH stdin from your shell. The backend requires `FS_TOKEN` here, unlike local
  dev, because this server is public. Optional, passed through when set in your shell:
  `GEMINI_API_KEY`, `DATABASE_URL` (Tiger Data copy of the event log), `SENTRY_DSN_BACKEND` and
  `SENTRY_DSN_WEB` (served to the pages by `GET /config`). Check with `curl https://<host>/health`:
  `eventDb.ok` and `sentry`.

## Use it

```sh
source .env.sh                                   # VULTR_API_KEY, FLOOR_SENSE_TOKEN, ELEVENLABS_API_KEY
backend/deploy/provision.sh                      # once: creates the server, prints its IP
backend/deploy/deploy.sh <ip> --env --agent      # first deploy: env file, ElevenLabs agent, services
backend/deploy/deploy.sh <ip>                    # every later deploy of the committed HEAD
```

- The Vultr API key's access list must include your current public IP (`curl -4 ifconfig.me`).
- SSH: `ssh -i ~/.ssh/floorsense_vultr root@<ip>`; logs: `journalctl -u floor-sense-backend -u
  floor-sense-voice -u caddy -f`.
- Pages: `https://<host>/app/index.html?token=<FS_TOKEN>` and `.../app/kitchen.html?token=...`.
- Glasses: `VITE_BACKEND_URL=wss://<host>/ws`, `VITE_FS_TOKEN=<FS_TOKEN>`, and the host listed in
  `glasses/app.json` as `https://<host>` and `wss://<host>` (Coder B's lane, then a new `.ehpk`).
- Stop paying: destroy the server in the Vultr dashboard (or `DELETE /v2/instances/<id>`).
