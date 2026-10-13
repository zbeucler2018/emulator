#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: infinity-blade-wine <game.exe>" >&2
    exit 64
fi

executable=$1
case "$executable" in
    /romm/library/roms/*) ;;
    *)
        echo "refusing executable outside /romm/library/roms: $executable" >&2
        exit 65
        ;;
esac

if [ ! -f "$executable" ]; then
    echo "game executable not found: $executable" >&2
    exit 66
fi

# Keep Sophia as the canonical library, but run from the persistent Box-side
# cache prepared by setup-infinity-blade.sh.  UE3 performs hundreds of
# thousands of small reads while its splash is open; doing those over the NAS
# made a normal launch take six minutes.  A missing cache remains a supported
# (slower) fallback.
game_key=${INFINITY_BLADE_GAME:-}
cache_root=${INFINITY_BLADE_CACHE_ROOT:-/config/infinity-blade/game-cache}
case "$game_key" in
    ib1|ib2|ib3)
        cached_executable=$(find "$cache_root/$game_key" -type f \
            -iname "$(basename "$executable")" -print -quit 2>/dev/null || true)
        if [ -n "$cached_executable" ] && [ -f "$cached_executable" ]; then
            executable=$cached_executable
        fi
        ;;
esac

cd "$(dirname "$executable")"

# WebStation normally exports only files whose mtimes changed after launch.
# Infinity Blade spreads progress across several INI files and may leave some
# of them byte-for-byte untouched in a session. A delta-only ZIP would then be
# unsafe to restore by itself. Touch the restored tree just after the broker
# records its launch baseline so every RomM save is a complete snapshot. Files
# the game creates later already have fresh mtimes and are included normally.
save_root="${WINEPREFIX:-/config/infinity-blade/prefix}/drive_c/users/${INFINITY_BLADE_WINE_USER:-abc}/Documents/My Games"
(
    sleep 2
    if [ -d "$save_root" ]; then
        find "$save_root" -type f -exec touch {} +
    fi
) &

# IB3's direct executable starts from mobile-oriented desktop defaults. Its
# renderer accepts UE3's resolution flags even though the outer Wine window is
# initially smaller; forcing the X11 parent or rewriting its generated INI
# makes the DX9 startup movie black. Leave those settings alone and pass only
# the launch flags that were verified to preserve the animated renderer.
case "$game_key" in
    ib3)
        exec "${INFINITY_BLADE_WINE_BIN:-wine}" "$executable" -ResX=1280 -ResY=720 -Fullscreen
        ;;
    *)
        exec "${INFINITY_BLADE_WINE_BIN:-wine}" "$executable"
        ;;
esac
