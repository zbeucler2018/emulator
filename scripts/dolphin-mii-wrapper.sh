#!/bin/sh
# Keep Dolphin's Wii Mii database shared while RomM continues to sync each
# game's remaining Wii NAND files independently.
set -eu

user_dir=${DOLPHIN_USER_DIR:-/config/.local/share/dolphin-emu}
shared_dir=${DOLPHIN_SHARED_MII_DIR:-/config/.romm-shared/dolphin-wii}
real_bin=${DOLPHIN_REAL_BIN:-/usr/local/bin/dolphin-emu}
live_db="$user_dir/Wii/shared2/menu/FaceLib/RFL_DB.dat"
shared_db="$shared_dir/RFL_DB.dat"

ensure_dirs() {
  mkdir -p "$(dirname "$live_db")" "$shared_dir"
}

same_file() {
  [ -e "$1" ] && [ -e "$2" ] && [ "$1" -ef "$2" ]
}

replace_shared_from_live() {
  tmp="$shared_dir/.RFL_DB.dat.$$"
  cp -p "$live_db" "$tmp"
  mv -f "$tmp" "$shared_db"
}

link_shared_into_nand() {
  ensure_dirs

  # On the first run, adopt a database created from the desktop or an older
  # unwrapped deployment. Never invent an empty database: Dolphin owns its
  # binary format and will create a valid one when the Mii editor is used.
  if [ ! -e "$shared_db" ] && [ -f "$live_db" ] && [ ! -L "$live_db" ]; then
    replace_shared_from_live
  fi

  if [ -e "$shared_db" ]; then
    if [ -e "$live_db" ] || [ -L "$live_db" ]; then
      if same_file "$live_db" "$shared_db"; then
        return
      fi
      [ -f "$live_db" ] || {
        echo "refusing to replace non-file Mii database path: $live_db" >&2
        exit 1
      }
      rm -f "$live_db"
    fi
    # A hard link behaves like an ordinary file to the broker's archive
    # safety checks. Clearing Wii/shared2 unlinks only this name; the shared
    # name outside Wii/ keeps the database inode alive.
    ln "$shared_db" "$live_db"
  fi
}

sync_live_back() {
  [ -f "$live_db" ] && [ ! -L "$live_db" ] || return 0

  # Dolphin may rewrite the file in place (the hard link already covers it)
  # or atomically replace it (copy the replacement back, then relink it).
  if ! same_file "$live_db" "$shared_db"; then
    replace_shared_from_live
    rm -f "$live_db"
    ln "$shared_db" "$live_db"
  fi
}

link_shared_into_nand

if [ "${1:-}" = "--prepare-only" ]; then
  exit 0
fi

set +e
"$real_bin" "$@"
status=$?
set -e
sync_live_back
exit "$status"
