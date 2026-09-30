#!/bin/sh
# WebStation's current PCSX2 package selects Vulkan automatically on this host.
# Its image lacks libshaderc, so Vulkan cannot initialise a render device even
# though NVIDIA is correctly available. Force PCSX2's NVIDIA OpenGL backend
# immediately before every broker launch; all other user settings stay in the
# persistent /config tree.
set -eu

config_root="${XDG_CONFIG_HOME:-/config/.config}/PCSX2"
ini_path="$config_root/inis/PCSX2.ini"
mkdir -p "$(dirname "$ini_path")"

if [ ! -f "$ini_path" ]; then
  printf '%s\n' '[UI]' 'SettingsVersion = 1' > "$ini_path"
fi

tmp_path="$ini_path.romm-opengl.$$"
awk '
  BEGIN { in_gs = 0; saw_gs = 0; wrote_renderer = 0 }
  /^\[EmuCore\/GS\]$/ {
    in_gs = 1
    saw_gs = 1
    print
    next
  }
  /^\[/ {
    if (in_gs && !wrote_renderer) {
      print "Renderer = 12"
      wrote_renderer = 1
    }
    in_gs = 0
  }
  in_gs && /^Renderer[[:space:]]*=/ {
    if (!wrote_renderer) print "Renderer = 12"
    wrote_renderer = 1
    next
  }
  { print }
  END {
    if (!saw_gs) print "\n[EmuCore/GS]"
    if (!wrote_renderer) print "Renderer = 12"
  }
' "$ini_path" > "$tmp_path"
mv "$tmp_path" "$ini_path"

exec /usr/games/pcsx2-qt "$@"
