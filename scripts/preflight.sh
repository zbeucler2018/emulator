#!/usr/bin/env bash
# Run this on the Ubuntu host before `docker compose up -d`.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$repo_root/.env"

[[ -f "$env_file" ]] || { echo "Missing $env_file; copy .env.example first." >&2; exit 1; }
set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

"$repo_root/scripts/mount-check.sh"

if [[ ! -d "$APP_DATA_PATH" ]]; then
  cat >&2 <<EOF
Application data directory does not exist: $APP_DATA_PATH
Create it once with:
  sudo install -d -o "$USER" -g "$(id -gn)" -m 0750 "$APP_DATA_PATH"
EOF
  exit 1
fi
if [[ ! -w "$APP_DATA_PATH" ]]; then
  cat >&2 <<EOF
Application data directory is not writable: $APP_DATA_PATH
Grant the deployment user ownership, for example:
  sudo chown "$USER":"$(id -gn)" "$APP_DATA_PATH"
EOF
  exit 1
fi

for dir in "$APP_DATA_PATH/mysql" "$APP_DATA_PATH/redis" "$APP_DATA_PATH/resources" "$ROMM_ASSETS_PATH" "$BACKUP_ROOT"; do
  install -d -m 0750 "$dir"
done

docker compose --env-file "$env_file" -f "$repo_root/docker-compose.yml" config --quiet
echo "Preflight passed. Start with: docker compose --env-file .env up -d"
