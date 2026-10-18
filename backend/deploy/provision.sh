#!/usr/bin/env bash
# Create the Floor Sense server on Vultr: Los Angeles, 1 vCPU / 2 GB, Ubuntu 24.04, first boot from
# cloud-init.yaml. Prints the server's IP; then run deploy.sh <ip> --env --agent.
#
#   source .env.sh && backend/deploy/provision.sh
#
# Reads VULTR_API_KEY from the shell (the key's access list must include this machine's IP).
# Creates the SSH key FS_SSH_KEY (default ~/.ssh/floorsense_vultr) if it doesn't exist. Running it
# again finds the existing "floor-sense" server instead of creating a second one.
set -euo pipefail

: "${VULTR_API_KEY:?source .env.sh first}"
KEY=${FS_SSH_KEY:-$HOME/.ssh/floorsense_vultr}
HERE=$(cd "$(dirname "$0")" && pwd)
API=https://api.vultr.com/v2
LABEL=floor-sense

api() { curl -4 -fsS --max-time 30 -H "Authorization: Bearer $VULTR_API_KEY" -H 'Content-Type: application/json' "$@"; }
log() { echo "[fs] $*" >&2; }

existing=$(api "$API/instances?per_page=500" | python3 -c '
import json, sys
mine = [i for i in json.load(sys.stdin)["instances"] if i["label"] == sys.argv[1]]
print(mine[0]["id"] if mine else "")' "$LABEL")
if [ -n "$existing" ]; then
  log "server $LABEL already exists ($existing)"
  id=$existing
else
  if [ ! -f "$KEY" ]; then
    mkdir -p -m 700 "$(dirname "$KEY")"
    ssh-keygen -q -t ed25519 -N '' -C floor-sense-deploy -f "$KEY"
    log "created SSH key $KEY"
  fi
  key_id=$(api "$API/ssh-keys" | python3 -c '
import json, sys
keys = [k for k in json.load(sys.stdin)["ssh_keys"] if k["name"] == "floor-sense-deploy"]
print(keys[0]["id"] if keys else "")')
  if [ -z "$key_id" ]; then
    key_id=$(python3 -c 'import json,sys; print(json.dumps({"name": "floor-sense-deploy", "ssh_key": open(sys.argv[1]).read().strip()}))' "$KEY.pub" \
      | api -X POST "$API/ssh-keys" --data-binary @- | python3 -c 'import json,sys; print(json.load(sys.stdin)["ssh_key"]["id"])')
    log "uploaded SSH key ($key_id)"
  fi
  payload=$(mktemp)
  python3 -c '
import base64, json, sys
key_id, user_data, label = sys.argv[1:]
print(json.dumps({
    "region": "lax",
    "plan": "vc2-1c-2gb",
    "os_id": 2284,  # Ubuntu 24.04 LTS x64
    "label": label,
    "hostname": label,
    "sshkey_id": [key_id],
    "user_data": base64.b64encode(open(user_data, "rb").read()).decode(),
    "backups": "disabled",
    "enable_ipv6": True,
}))' "$key_id" "$HERE/cloud-init.yaml" "$LABEL" > "$payload"
  id=$(api -X POST "$API/instances" --data-binary @"$payload" | python3 -c 'import json,sys; print(json.load(sys.stdin)["instance"]["id"])')
  rm -f "$payload"
  log "created server $LABEL ($id), waiting for it to boot"
fi

for _ in $(seq 1 60); do
  read -r status ip < <(api "$API/instances/$id" | python3 -c 'import json,sys; i=json.load(sys.stdin)["instance"]; print(i["status"], i["main_ip"])')
  if [ "$status" = active ] && [ "$ip" != 0.0.0.0 ]; then
    log "active at $ip"
    echo "$ip"
    exit 0
  fi
  sleep 10
done
log "server $id did not become active in 10 minutes"
exit 1
