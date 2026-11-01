#!/usr/bin/env bash
set -euo pipefail

# Non-destructive host-side validation for the optional Steam profile.  This
# deliberately does not issue a game launch or touch the host Steam library.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

docker compose --profile steam config --quiet

container_id="$(docker compose --profile steam ps -q steam)"
if [[ -z "$container_id" ]]; then
  echo "Steam service is not running" >&2
  exit 1
fi

health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")"
if [[ "$health" != "healthy" ]]; then
  echo "Steam service health is $health" >&2
  exit 1
fi

http_port="${STEAM_HTTP_PORT:-3020}"
unauthenticated_status="$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:${http_port}/steam/")"
if [[ "$unauthenticated_status" != "401" ]]; then
  echo "Expected unauthenticated Steam UI to return 401, got $unauthenticated_status" >&2
  exit 1
fi

password_file="${STEAM_WEB_PASSWORD_FILE:-/srv/emulator/steam-web-password}"
web_user="${STEAM_WEB_USER:-steam}"
curl -fsS -u "${web_user}:$(<"$password_file")" \
  "http://127.0.0.1:${http_port}/steam/" >/dev/null

docker exec "$container_id" curl -fsS http://127.0.0.1:8000/health >/dev/null
docker exec "$container_id" nvidia-smi --query-gpu=name,driver_version \
  --format=csv,noheader
docker exec "$container_id" sh -eu -c '
  test -L /config/.local/share/Steam/steamapps/common/Valheim ||
    find /config/.local/share/Steam/steamapps/common -maxdepth 1 -type l | grep -q .
  test "$(findmnt -n -o OPTIONS -T /mnt/host-steam | tr , "\n" | grep -xc ro)" = 1
'

echo "Steam smoke test passed: authenticated UI, broker, NVIDIA GPU, and read-only zero-copy library"
