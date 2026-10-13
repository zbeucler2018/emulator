#!/bin/bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_dir"

if [[ ! -f .env ]]; then
    echo "Missing $repo_dir/.env; configure the deployment first." >&2
    exit 1
fi

echo "Building the derived WebStation image with Wine..."
docker compose --env-file .env build romm-webstation

set -a
# shellcheck disable=SC1091
source .env
set +a

cache_root="${WEBSTATION_CONFIG_PATH:?set WEBSTATION_CONFIG_PATH in .env}/infinity-blade/game-cache"
mkdir -p "$cache_root"

echo "Refreshing the Box-side game cache from Sophia..."
while IFS='|' read -r key directory; do
    source_dir="${ROM_LIBRARY_PATH:?set ROM_LIBRARY_PATH in .env}/Windows/$directory"
    if [[ ! -d "$source_dir" ]]; then
        echo "  $directory: not installed; skipping cache" >&2
        continue
    fi
    mkdir -p "$cache_root/$key"
    rsync -a --delete "$source_dir/" "$cache_root/$key/"
    echo "  $directory: cached"
done <<'GAMES'
ib1|Infinity Blade
ib2|Infinity Blade II
ib3|Infinity Blade III
GAMES

chown -R "${WEBSTATION_PUID:-1000}:${WEBSTATION_PGID:-1000}" "$cache_root"

echo "Starting the Wine-enabled WebStation service..."
docker compose --env-file .env up -d romm-webstation

marker=/config/infinity-blade/prefix/.infinity-blade-runtime-ready
if docker compose --env-file .env exec -T -u abc romm-webstation test -f "$marker"; then
    echo "Infinity Blade Wine runtime is already initialized."
else
    echo "Initializing the persistent Wine prefix and Microsoft runtimes..."
    docker compose --env-file .env exec -T -u abc romm-webstation \
        mkdir -p /config/infinity-blade/prefix
    docker compose --env-file .env exec -T -u abc \
        -e HOME=/config \
        -e WINEPREFIX=/config/infinity-blade/prefix \
        -e WINEARCH=win64 \
        romm-webstation xvfb-run -a wineboot --init
    docker compose --env-file .env exec -T -u abc \
        -e HOME=/config \
        -e WINEPREFIX=/config/infinity-blade/prefix \
        -e WINEARCH=win64 \
        romm-webstation xvfb-run -a winetricks -q vcrun2010 d3dx9
    docker compose --env-file .env exec -T -u abc romm-webstation \
        touch "$marker"
fi

echo
echo "Installed game detection:"
docker compose --env-file .env exec -T -u abc romm-webstation python3 - <<'PY'
from pathlib import Path
from infinity_blade import resolve_game

root = Path("/romm/library/roms/Windows")
if not root.is_dir():
    print("  none: /mnt/sophia/games/Windows has not been created")
else:
    found = False
    for path in sorted(root.iterdir()):
        game, executable = resolve_game(path)
        if game is not None:
            found = True
            status = str(executable) if executable else "missing a supported executable"
            print(f"  {path.name}: {status}")
    if not found:
        print("  none")
PY

echo
echo "Runtime setup complete. Add legal, extracted game files as documented in docs/infinity-blade.md."
