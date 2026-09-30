#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT HUP INT TERM

user_dir="$test_root/user"
shared_dir="$test_root/shared"
live_db="$user_dir/Wii/shared2/menu/FaceLib/RFL_DB.dat"
shared_db="$shared_dir/RFL_DB.dat"
fake_dolphin="$test_root/fake-dolphin"

mkdir -p "$(dirname "$live_db")"
printf 'desktop-mii\n' > "$live_db"

DOLPHIN_USER_DIR="$user_dir" \
DOLPHIN_SHARED_MII_DIR="$shared_dir" \
  "$repo_root/scripts/dolphin-mii-wrapper.sh" --prepare-only

[ "$live_db" -ef "$shared_db" ]
[ "$(cat "$shared_db")" = "desktop-mii" ]

# Simulate the broker clearing Wii/shared2 and restoring an older per-game
# copy. The shared copy must win when Dolphin is launched.
rm -rf "$user_dir/Wii/shared2"
mkdir -p "$(dirname "$live_db")"
printf 'stale-game-copy\n' > "$live_db"

cat > "$fake_dolphin" <<'EOF'
#!/bin/sh
replacement="$DOLPHIN_TEST_LIVE_DB.new"
printf 'game-updated-mii\n' > "$replacement"
mv -f "$replacement" "$DOLPHIN_TEST_LIVE_DB"
EOF
chmod +x "$fake_dolphin"

DOLPHIN_USER_DIR="$user_dir" \
DOLPHIN_SHARED_MII_DIR="$shared_dir" \
DOLPHIN_REAL_BIN="$fake_dolphin" \
DOLPHIN_TEST_LIVE_DB="$live_db" \
  "$repo_root/scripts/dolphin-mii-wrapper.sh" --batch test.rvz

[ "$live_db" -ef "$shared_db" ]
[ "$(cat "$shared_db")" = "game-updated-mii" ]

printf 'dolphin Mii persistence wrapper: ok\n'
