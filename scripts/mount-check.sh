#!/bin/sh
# Fail closed if the Corsair CIFS share is missing or a local directory replaced it.
set -eu

games_mount="${GAMES_MOUNT:-/mnt/games}"
rom_library="${ROM_LIBRARY_PATH:-${games_mount}/roms}"
assets_path="${ROMM_ASSETS_PATH:-${games_mount}/saves/romm-assets}"
nas_server="${NAS_SERVER:-corsair}"
nas_share="${NAS_SHARE:-games}"
nas_marker="${NAS_MARKER:-.emulator-nas-marker}"

fail() { printf '%s\n' "mount check: $*" >&2; exit 1; }

[ -d "$games_mount" ] || fail "missing games mount directory: $games_mount"
[ -d "$rom_library" ] || fail "missing ROM library: $rom_library"
[ -d "$assets_path" ] || fail "missing RomM asset directory: $assets_path"
[ -f "$games_mount/$nas_marker" ] || fail "missing NAS marker: $games_mount/$nas_marker"

if command -v findmnt >/dev/null 2>&1; then
  fs_type="$(findmnt -n -o FSTYPE -T "$games_mount" 2>/dev/null || true)"
  source="$(findmnt -n -o SOURCE -T "$games_mount" 2>/dev/null || true)"
  [ "$fs_type" = "cifs" ] || fail "$games_mount is $fs_type, expected cifs"
  case "$source" in
    "//$nas_server/$nas_share"*|"//$nas_server"*) ;;
    *) fail "mounted source '$source' does not match //$nas_server/$nas_share" ;;
  esac
else
  # Alpine mount-guard does not include findmnt. A bind mount of a CIFS share
  # is still represented as cifs in mountinfo on supported Docker hosts.
  grep -Eq " - cifs .*$" /proc/self/mountinfo || fail "no cifs filesystem visible in container"
fi

printf 'mount check: NAS share %s is available at %s\n' "$nas_server/$nas_share" "$games_mount"
