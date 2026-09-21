#!/usr/bin/env bash
# Create rolling, timestamped snapshots of RomM assets on the NAS.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$repo_root/.env"
[[ -f "$env_file" ]] || { echo "Missing $env_file" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

"$repo_root/scripts/mount-check.sh"
: "${ROMM_ASSETS_PATH:?}" "${BACKUP_ROOT:?}" "${SAVE_BACKUP_RETENTION:=20}"
[[ "$ROMM_ASSETS_PATH" != / && "$BACKUP_ROOT" != / ]] || { echo "Refusing unsafe root path" >&2; exit 1; }
[[ "$SAVE_BACKUP_RETENTION" =~ ^[1-9][0-9]*$ ]] || { echo "SAVE_BACKUP_RETENTION must be a positive integer" >&2; exit 1; }

install -d -m 0750 "$BACKUP_ROOT/snapshots"
lock_file="$BACKUP_ROOT/.backup.lock"
exec 9>"$lock_file"
flock -n 9 || { echo "A save backup is already running." >&2; exit 1; }

timestamp="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
snapshot="$BACKUP_ROOT/snapshots/$timestamp"
mkdir "$snapshot"
rsync -a --human-readable --itemize-changes "$ROMM_ASSETS_PATH/" "$snapshot/"
printf '%s\n' "$(date -u +%FT%TZ) $timestamp" > "$BACKUP_ROOT/last-successful-backup"

mapfile -t snapshots < <(find "$BACKUP_ROOT/snapshots" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
excess=$(( ${#snapshots[@]} - SAVE_BACKUP_RETENTION ))
if (( excess > 0 )); then
  for old_snapshot in "${snapshots[@]:0:excess}"; do
    case "$old_snapshot" in
      ????-??-??T??-??-??Z) rm -rf -- "$BACKUP_ROOT/snapshots/$old_snapshot" ;;
      *) echo "Refusing to delete unexpected backup name: $old_snapshot" >&2; exit 1 ;;
    esac
  done
fi

echo "Saved snapshot: $snapshot"
