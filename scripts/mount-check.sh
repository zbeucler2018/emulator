#!/bin/sh
# Fail closed if the configured storage mount is missing or a plain directory
# on the host root filesystem replaced it.
set -eu

games_mount="${GAMES_MOUNT:-/mnt/games}"
rom_library="${ROM_LIBRARY_PATH:-${games_mount}/roms}"
assets_path="${ROMM_ASSETS_PATH:-${games_mount}/saves/romm-assets}"
nas_server="${NAS_SERVER:-corsair}"
nas_share="${NAS_SHARE:-games}"
nas_marker="${NAS_MARKER:-.emulator-nas-marker}"
storage_type="${STORAGE_TYPE:-cifs}"
expected_fs_type="${EXPECTED_FS_TYPE:-$storage_type}"

fail() { printf '%s\n' "mount check: $*" >&2; exit 1; }

[ -d "$games_mount" ] || fail "missing games mount directory: $games_mount"
[ -d "$rom_library" ] || fail "missing ROM library: $rom_library"
[ -d "$assets_path" ] || fail "missing RomM asset directory: $assets_path"
[ -f "$games_mount/$nas_marker" ] || fail "missing NAS marker: $games_mount/$nas_marker"

if command -v findmnt >/dev/null 2>&1; then
  # A systemd automount can make findmnt report both an autofs layer and the
  # backing filesystem. Select the configured filesystem explicitly.
  fs_type="$(findmnt -n -t "$expected_fs_type" -o FSTYPE -T "$games_mount" 2>/dev/null || true)"
  source="$(findmnt -n -t "$expected_fs_type" -o SOURCE -T "$games_mount" 2>/dev/null || true)"
  [ "$fs_type" = "$expected_fs_type" ] || fail "$games_mount is $fs_type, expected $expected_fs_type"
  if [ "$storage_type" = "cifs" ]; then
    case "$source" in
      "//$nas_server/$nas_share"*|"//$nas_server"*) ;;
      *) fail "mounted source '$source' does not match //$nas_server/$nas_share" ;;
    esac
  fi
else
  # Alpine mount-guard does not include findmnt. Docker bind mounts retain the
  # backing filesystem type in mountinfo, for both CIFS and local ext4 storage.
  grep -Eq " - ${expected_fs_type} .*$" /proc/self/mountinfo || fail "no $expected_fs_type filesystem visible in container"
fi

if [ "$storage_type" = "cifs" ]; then
  printf 'mount check: NAS share %s is available at %s\n' "$nas_server/$nas_share" "$games_mount"
else
  printf 'mount check: local %s storage is available at %s\n' "$expected_fs_type" "$games_mount"
fi
