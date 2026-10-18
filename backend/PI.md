# Running the backend on a Raspberry Pi 5

Measured on the Mac (2026-10-18): the backend's physical footprint is 44 MB idle and 48 MB peak while
`scripts/task_walkthrough.py` drives three sockets through every task state. Any Pi 5 (1 GB and up) has
plenty of room; the Pi only runs the backend, never the glasses app or a model.

## 1. Flash and boot (needs a person)

1. Raspberry Pi Imager, choose **Raspberry Pi OS Lite (64-bit)** (Bookworm ships Python 3.11).
2. In the Imager's settings: hostname `floorsense`, enable SSH, set a user, and enter the Wi-Fi.
3. Boot it and check from the Mac: `ssh <user>@floorsense.local`.

## 2. Install the backend (on the Pi)

```sh
sudo apt update && sudo apt install -y git
git clone https://github.com/Boycham/g2Rest.git && cd g2Rest/backend
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.local/bin/env
uv venv --python 3.11 .venv && uv pip install -r requirements.txt
```

Copy the keys from the Mac, never through chat or git: `scp .env <user>@floorsense.local:g2Rest/.env`.

Smoke test: `FS_TOKEN= .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8788`, then
`curl localhost:8788/health` in a second shell.

## 3. Keep it running (systemd)

```sh
sudo tee /etc/systemd/system/floorsense.service >/dev/null <<UNIT
[Unit]
Description=Floor Sense backend
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$HOME/g2Rest/backend
Environment=FS_TOKEN=
ExecStart=$HOME/g2Rest/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8788
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl enable --now floorsense && systemctl status floorsense --no-pager
```

## 4. Reach it from the phone (needs a person)

```sh
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up            # sign in to the same tailnet as the Mac
sudo tailscale funnel --bg --set-path /fs 8788   # makes the backend public
```

The phone then uses `wss://floorsense.tail1c4bf3.ts.net/fs/ws`. That host has to be added to
`glasses/app.json` (glasses lane) before the app can call it. Turn the Mac's `/fs` funnel off so only one
backend is live.

HW-PENDING: not yet run on the Pi itself.
