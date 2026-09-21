#!/usr/bin/env bash
# Small operational check suitable for cron, systemd, or a monitoring probe.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$repo_root/.env"
[[ -f "$env_file" ]] || { echo "Missing $env_file" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

"$repo_root/scripts/mount-check.sh"
docker compose --env-file "$env_file" -f "$repo_root/docker-compose.yml" ps --status running --services | grep -qx romm
curl --fail --silent --show-error "http://127.0.0.1:${ROMM_PORT:-8080}/" >/dev/null

if [[ -f "$BACKUP_ROOT/last-successful-backup" ]]; then
  echo "Last save backup: $(cat "$BACKUP_ROOT/last-successful-backup")"
else
  echo "Warning: no successful save backup recorded yet" >&2
fi
echo "Health check passed."
