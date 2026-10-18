#!/usr/bin/env bash
# Ship the backend, voice relay and web pages to the Floor Sense server and (re)start them.
#
#   source .env.sh && backend/deploy/deploy.sh <server-ip> [--env] [--agent]
#
#   --env    (re)write /etc/floor-sense/env from your shell: FLOOR_SENSE_TOKEN (the backend's
#            FS_TOKEN), ELEVENLABS_API_KEY and, if set, ELEVENLABS_AGENT_ID,
#            ELEVENLABS_TALK_AGENT_ID, GEMINI_API_KEY, DATABASE_URL (Tiger Data event log),
#            SENTRY_DSN_BACKEND, SENTRY_DSN_WEB and SENTRY_ENVIRONMENT. Agent ids already on the
#            server are kept unless the shell sends new ones. Secrets go over SSH stdin, never into
#            the repo or a command line.
#   --agent  create the two ElevenLabs agents on the server (create_agent.py: the clip-order agent
#            and the clip's "talk" agent) and put their ids in the env file. Needed once, and again
#            after their prompts or tools change. Old agents stay in the ElevenLabs account.
#
# Deploys the committed tree at FS_DEPLOY_REF (default HEAD); uncommitted changes are not shipped.
# web/verity (React + Vite) is built from that same tree on this machine, so it needs Node and npm.
set -euo pipefail

IP=${1:?usage: deploy.sh <server-ip> [--env] [--agent]}
shift
WRITE_ENV=0
MAKE_AGENT=0
for arg in "$@"; do
  case $arg in
    --env) WRITE_ENV=1 ;;
    --agent) MAKE_AGENT=1 ;;
    *) echo "unknown option $arg" >&2; exit 2 ;;
  esac
done

KEY=${FS_SSH_KEY:-$HOME/.ssh/floorsense_vultr}
REF=${FS_DEPLOY_REF:-HEAD}
HOST="${IP//./-}.sslip.io"
ROOT=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 "root@$IP")
log() { echo "[fs] $*" >&2; }

log "waiting for SSH and first boot on $IP"
# Vultr reports a new server "active" before sshd is up, so retry for a few minutes.
for _ in $(seq 1 40); do
  "${SSH[@]}" true 2>/dev/null && break
  sleep 8
done
"${SSH[@]}" 'cloud-init status --wait >/dev/null 2>&1 || true; command -v caddy >/dev/null && id floorsense >/dev/null'

if [ "$WRITE_ENV" = 1 ]; then
  : "${FLOOR_SENSE_TOKEN:?set FLOOR_SENSE_TOKEN (the server FS_TOKEN)}" "${ELEVENLABS_API_KEY:?set ELEVENLABS_API_KEY}"
  {
    echo "FS_TOKEN=$FLOOR_SENSE_TOKEN"
    echo "ELEVENLABS_API_KEY=$ELEVENLABS_API_KEY"
    [ -n "${ELEVENLABS_AGENT_ID:-}" ] && echo "ELEVENLABS_AGENT_ID=$ELEVENLABS_AGENT_ID"
    [ -n "${ELEVENLABS_TALK_AGENT_ID:-}" ] && echo "ELEVENLABS_TALK_AGENT_ID=$ELEVENLABS_TALK_AGENT_ID"
    [ -n "${GEMINI_API_KEY:-}" ] && echo "GEMINI_API_KEY=$GEMINI_API_KEY"
    [ -n "${DATABASE_URL:-}" ] && echo "DATABASE_URL=$DATABASE_URL"
    [ -n "${SENTRY_DSN_BACKEND:-}" ] && echo "SENTRY_DSN_BACKEND=$SENTRY_DSN_BACKEND"
    [ -n "${SENTRY_DSN_WEB:-}" ] && echo "SENTRY_DSN_WEB=$SENTRY_DSN_WEB"
    [ -n "${SENTRY_ENVIRONMENT:-}" ] && echo "SENTRY_ENVIRONMENT=$SENTRY_ENVIRONMENT"
    true
  } | "${SSH[@]}" 'set -e; umask 027; cd /etc/floor-sense; cat > env.new
      # keep the agents made by --agent unless the shell sent new ids
      for name in ELEVENLABS_AGENT_ID ELEVENLABS_TALK_AGENT_ID; do
        if ! grep -q "^$name=" env.new && [ -f env ]; then grep "^$name=" env >> env.new || true; fi
      done
      chgrp floorsense env.new && mv env.new env'
  log "wrote /etc/floor-sense/env"
fi

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
git -C "$ROOT" archive --format=tar "$REF" backend data web | tar -x -C "$STAGE"
if [ -f "$STAGE/web/verity/package.json" ]; then
  log "building web/verity from $(git -C "$ROOT" rev-parse --short "$REF")"
  (
    cd "$STAGE/web/verity"
    { npm ci --no-audit --no-fund --loglevel=error && npm run build; } > "$STAGE/verity-build.log" 2>&1 \
      || { tail -20 "$STAGE/verity-build.log" >&2; exit 1; }
  )
  rm -rf "$STAGE/web/verity/node_modules"
fi

log "shipping $(git -C "$ROOT" rev-parse --short "$REF") (backend, data, web)"
COPYFILE_DISABLE=1 tar -C "$STAGE" --no-xattrs -cf - backend data web \
  | "${SSH[@]}" 'rm -rf /opt/floor-sense/app.new && mkdir -p /opt/floor-sense/app.new && tar -x -C /opt/floor-sense/app.new \
      && rm -rf /opt/floor-sense/app && mv /opt/floor-sense/app.new /opt/floor-sense/app && chown -R floorsense:floorsense /opt/floor-sense'

"${SSH[@]}" "FS_HOST=$HOST bash -s" <<'EOF'
set -euo pipefail
cd /opt/floor-sense
[ -x venv-backend/bin/python ] || sudo -u floorsense python3 -m venv venv-backend
[ -x venv-voice/bin/python ] || sudo -u floorsense python3 -m venv venv-voice
sudo -u floorsense venv-backend/bin/pip install -q --no-cache-dir -r app/backend/requirements.txt
sudo -u floorsense venv-voice/bin/pip install -q --no-cache-dir -r app/backend/voice/requirements.txt
install -m 644 app/backend/deploy/floor-sense-backend.service app/backend/deploy/floor-sense-voice.service /etc/systemd/system/
sed "s/__FS_HOST__/$FS_HOST/g" app/backend/deploy/Caddyfile > /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable -q floor-sense-voice floor-sense-backend
systemctl reload-or-restart caddy
EOF

if [ "$MAKE_AGENT" = 1 ]; then
  log "creating the ElevenLabs clip-order and talk agents on the server"
  "${SSH[@]}" 'set -euo pipefail; cd /opt/floor-sense/app/backend/voice
    set -a; . /etc/floor-sense/env; set +a
    py() { sudo -u floorsense --preserve-env=ELEVENLABS_API_KEY /opt/floor-sense/venv-voice/bin/python "$@"; }
    py create_agent.py --mode clip >/dev/null
    py create_agent.py --mode talk >/dev/null
    agent=$(tr -d "[:space:]" < .agent_id)
    talk=$(tr -d "[:space:]" < .talk_agent_id)
    sed -i "/^ELEVENLABS_AGENT_ID=/d; /^ELEVENLABS_TALK_AGENT_ID=/d" /etc/floor-sense/env
    printf "ELEVENLABS_AGENT_ID=%s\nELEVENLABS_TALK_AGENT_ID=%s\n" "$agent" "$talk" >> /etc/floor-sense/env
    echo "[fs] agents $agent (clip) and $talk (talk) added to /etc/floor-sense/env" >&2'
fi

"${SSH[@]}" 'systemctl restart floor-sense-voice floor-sense-backend'
log "waiting for https://$HOST/health"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 "https://$HOST/health" >/dev/null 2>&1; then
    log "up: https://$HOST"
    log "pages (add ?token=): https://$HOST/app/index.html, /app/kitchen.html, /app/verity/dist/dashboard.html"
    exit 0
  fi
  sleep 3
done
log "health check failed; on the server: journalctl -u floor-sense-backend -u floor-sense-voice -u caddy -n 50"
exit 1
