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

cd "$(dirname "$executable")"
exec "${INFINITY_BLADE_WINE_BIN:-wine}" "$executable"
