# Mario Kart Wii: Retro Rewind

This integration makes Retro Rewind a separate Wii catalogue item in RomM and
launches it directly through the existing WebStation/Selkies session. Wheel
Wizard is not required at runtime, vanilla Mario Kart Wii is not modified, and
the existing Dolphin Mii wrapper remains the outermost broker launcher.

## Current deployment state

The non-disruptive data preparation was completed on 2026-10-27:

- Base game: `Mario Kart Wii (USA) (En,Fr,Es).rvz`, game ID `RMCE01`, NTSC-U,
  revision 0, at `/mnt/games/Sophia/games/Wii/`.
- Official Retro Rewind: 6.13.4 under
  `/srv/emulator/retro-rewind/releases/6.13.4` (2.1 GB extracted).
- Download SHA-256:
  `586b929de36018e5fc3f7ee73b0aba407730d38470d7a54b8a455dca14be7002`.
- Active release: `/srv/emulator/retro-rewind/current`.
- Dolphin descriptor:
  `/srv/emulator/retro-rewind/launch/RetroRewind.json`.
- RomM launcher marker:
  `/mnt/games/Sophia/games/Wii/Mario Kart Wii - Retro Rewind.dol`.

Production activation was completed on 2026-10-27. WebStation has the scoped
launcher and read-only pack mount, and the Wii quick scan indexed the marker as
RomM ROM ID 2730. A real streamed race, physical two-controller input, and the
save/upload round trip still require hands-on validation.

## Why this architecture

Wheel Wizard's current source obtains the pack from the official
`https://update.rwfc.net/` manifest and builds a Dolphin
`dolphin-game-mod-descriptor` JSON. It has no supported headless installer
interface. Its GUI, updater process, and Dolphin discovery are therefore not
kept in the server runtime. The focused installer reproduces the relevant
official flow and records provenance. See the [Wheel Wizard source](https://github.com/TeamWheelWizard/WheelWizard),
[release history](https://github.com/TeamWheelWizard/WheelWizard/releases),
and [MKWiiki overview](https://www.mkwiiki.org/wiki/Wheel_Wizard).

```text
RomM Wii item: Mario Kart Wii - Retro Rewind.dol (small owned marker)
  -> WebStation broker: normal Dolphin lifecycle and per-ROM save archive
    -> existing dolphin-mii-wrapper.sh: shared RFL_DB.dat preservation
      -> dolphin-retro-rewind-wrapper.py: marker only -> RetroRewind.json
        -> Dolphin 2609a: RMCE01 RVZ + official RetroRewind6.xml/assets
          -> existing Selkies video/audio + four indexed virtual SDL pads
```

The marker is used because RomM and WebStation 0.15.1 do not index a Dolphin
Riivolution JSON as an ordinary Wii ROM. WebStation does accept `.dol`; the
scoped wrapper translates only the exact marker with the expected file
signature. Every other Wii and GameCube command is passed to Dolphin unchanged.
The descriptor format and option names match Wheel Wizard's own generator:
`Pack=1`, `My Stuff=0`. The stable pack does not select its misspelled
`Seperate Savegame` option because RomM already gives the marker an isolated
save identity.

The chosen Dolphin path is the supported Riivolution implementation, not
WiiCompiled. The installed Dolphin is 2609a. Wheel Wizard currently treats
2606a (or development build 2606-300) as its safe minimum.

## Prerequisites and validation

The installer supports `.iso`, `.wbfs`, `.rvz`, `.wia`, `.gcz`, and `.ciso`.
Raw ISO/WBFS headers are read directly. Compressed images are inspected with
the running WebStation container's `dolphin-tool`; no game is booted. It accepts
retail RMCE01, RMCP01, and RMCJ01 revision 0 and refuses other titles or
revisions.

Safe while other services are running:

```bash
cd ~/repos/emulator
./scripts/retro_rewind.py status --online
./scripts/retro_rewind.py install --dry-run
python3 -m unittest discover -s tests -p 'test*.py' -v
python3 tests/test-infinity-blade-launcher.py
./tests/test-dolphin-mii-wrapper.sh
docker compose --env-file ~/repos/emulator/.env -f docker-compose.yml config --quiet
```

`install` and `rollback` query the WebStation container and refuse to change
the active release while `dolphin-emu` is running. No command stops an emulator.

## Installation and updates

For a new host, preview and then install:

```bash
./scripts/retro_rewind.py install --dry-run
./scripts/retro_rewind.py install
```

The install command:

1. discovers and validates the existing backup;
2. reads the official install/version manifests over HTTPS;
3. downloads into a temporary directory under the destination filesystem;
4. calculates SHA-256, rejects unsafe ZIP paths/symlinks, and extracts with
   size/file-count limits;
5. validates `version.txt`, `RetroRewind6.xml`, and `Binaries/Code.pul`;
6. publishes `releases/<version>` and atomically swaps `current` only after all
   checks pass;
7. records `romm-install.json`, writes the launch JSON, and publishes the
   signed marker without touching the original RVZ.

The official server does not publish a detached checksum. TLS and the
official manifest establish the source; the calculated SHA-256 is recorded so
the exact installed archive can be audited. A manually obtained archive can
be required to match a trusted checksum:

```bash
./scripts/retro_rewind.py install \
  --archive '/path/to/6.13.4-full.zip' \
  --version 6.13.4 \
  --sha256 586b929de36018e5fc3f7ee73b0aba407730d38470d7a54b8a455dca14be7002
```

To check and update later (never during a Dolphin session):

```bash
./scripts/retro_rewind.py status --online
./scripts/retro_rewind.py install --dry-run
./scripts/retro_rewind.py install
```

Updates are full, atomic official-pack installs rather than replaying years of
incremental deletion lists. Existing releases are retained; nothing updates
automatically at game launch.

Rollback swaps symlinks and does not delete either release:

```bash
./scripts/retro_rewind.py rollback --dry-run
./scripts/retro_rewind.py rollback
# Or select a retained release explicitly:
./scripts/retro_rewind.py rollback --version 6.13.4
```

## Saves, licenses, Miis, and backups

The official XML redirects its cloned Mario Kart save to
`/riivolution/save/RetroWFC/<game+region>` beneath the descriptor root. Left
there, WebStation would not upload it to RomM. Each installed release instead
contains this container-only link:

```text
current/riivolution/save
  -> /config/.local/share/dolphin-emu/Wii/riivolution-save
```

The scoped wrapper creates the target after the broker restores the selected
game. It therefore lives inside the exact `Wii` subtree WebStation clears,
restores, and archives per RomM user and ROM. Retro Rewind licenses, progress,
settings, redirected `rksys.dat`, and relevant Pulsar data travel with the
Retro Rewind catalogue item instead of vanilla Mario Kart Wii. The original
game's RomM archive is unchanged.

`dolphin-mii-wrapper.sh` still hard-links only
`Wii/shared2/menu/FaceLib/RFL_DB.dat` to
`/config/.romm-shared/dolphin-wii/RFL_DB.dat`, so both entries see the shared
console Mii database without weakening other save isolation.

Back up both:

- RomM per-user save archives:
  `/mnt/games/Sophia/games/saves/romm-assets` (already covered by
  `scripts/backup-saves.sh`).
- Pack/provenance and shared Mii data:
  `/srv/emulator/retro-rewind` and
  `/srv/emulator/webstation/.romm-shared/dolphin-wii`.

Use the in-game save as the durable source. Dolphin save states contain
version-specific emulation and mod state; do not resume an old state after a
Retro Rewind update unless it has been tested with that version.

## Two local players

Selkies 2.0 polls four browser Gamepad API indices independently and the live
server exposes four independent virtual joystick sockets. A runtime SDL probe
confirmed indices 0-3 all appear to Dolphin as separate `Xbox 360 Controller`
devices. Stock secured Selkies 2.0 nevertheless rewrites every local pad from
the hosting browser to collaboration slot 0. The WebStation image carries an
exact-version compatibility patch that preserves each Gamepad API index for
the host while leaving remote viewers pinned to their assigned collaboration
slot. The Retro Rewind launch layer enables exactly two GameCube controller
ports and binds them explicitly:

- Player 1: `SDL/0/Xbox 360 Controller`
- Player 2: `SDL/1/Xbox 360 Controller`

Both receive their own complete button/stick/trigger mapping through Dolphin's
command-line configuration layer. Persistent global `GCPadNew.ini` is not
rewritten, so other games retain their mappings. Wii Remote Bluetooth or
VirtualHere is not used.

Client setup:

1. Pair or plug both standard controllers into the same laptop/iPad before
   opening the stream.
2. In the browser, press a button on controller 1 and then controller 2 so the
   Gamepad API exposes both devices. The first browser index is player 1.
3. Launch **Mario Kart Wii: Retro Rewind** and choose the game's two-player
   local mode.
4. If either controller disconnects, reconnect both, close the stream tab, and
   reopen it in player order. Browser Gamepad API indices—not Bluetooth MACs—are
   the assignment boundary; this reload prevents an unnoticed reorder.

Chromium on Linux is the primary validation target. Current Safari/iPadOS can
expose supported Bluetooth/USB controllers, but the two-physical-controller
iPad path still requires hands-on validation. The automated/runtime checks
prove browser slots remain distinct through Selkies and into SDL; they do not
prove a particular pair of client controllers or browser firmware.

RomM's **Multiplayer** switch is for a controller connected to a second
browser/device. Launch with Multiplayer enabled, create a **Player** invite,
and open it on the second device. The custom image assigns each Player invite
the first free gamepad automatically (normally Gamepad 2); a **Spectator**
invite stays unassigned and cannot send input. Upstream WebStation only made a
Player eligible for control and required the host to drag a numbered gamepad
icon onto the guest tile, which made a correctly connected iPhone appear
input-dead. The host can still drag gamepad icons between tiles to override
the automatic assignment.

Read-only SDL visibility probe:

```bash
docker cp tests/sdl-gamepad-probe.c emulator-romm-webstation-1:/tmp/sdl-gamepad-probe.c
docker exec emulator-romm-webstation-1 \
  gcc -O2 -Wall -Wextra /tmp/sdl-gamepad-probe.c \
  -Wl,-l:libSDL2-2.0.so.0 -o /tmp/sdl-gamepad-probe
docker exec emulator-romm-webstation-1 env \
  LD_PRELOAD=/usr/lib/selkies_input_interposer.so:/opt/lib/libudev.so.1.0.0-fake \
  /tmp/sdl-gamepad-probe
```

Expected output begins with `count=4` and lists four `Xbox 360 Controller`
indices.

## Rendering profile

Only the marker launch receives these settings:

- Vulkan on the RTX 4070 Ti;
- 3x internal resolution (1920x1584 before aspect/output scaling);
- exclusive ubershaders plus cached-shader compilation before start;
- 16x anisotropic filtering;
- automatic/native aspect ratio and no widescreen stretch;
- 60 FPS game timing left unmodified.

Dolphin's [performance guide](https://dolphin-emu.org/docs/guides/performance-guide/)
documents Vulkan as a strong NVIDIA backend and exclusive ubershaders as the
stutter-minimizing, high-GPU-cost choice. The 4070 Ti has ample headroom at 3x,
including split-screen, but sustained 60 FPS has not yet been measured in a
real streamed race.

Selkies remains 1280x720 for Infinity Blade compatibility. Higher internal
resolution improves geometry/texture sampling before downsampling; it does not
increase stream resolution. To try 4x after validating 3x, set
`RETRO_REWIND_INTERNAL_RESOLUTION=4` in `.env` and recreate only WebStation.
No HD texture pack is installed; the official Retro Rewind tracks, characters,
music, and assets are present.

## Deployment and final validation

These steps interrupt WebStation/Selkies sessions. Run them only when nobody
is playing a streamed game. RomM and its database do not need recreation.

```bash
cd ~/repos/emulator
git status --short
git pull --ff-only
docker compose --env-file .env config --quiet
docker compose --env-file .env up -d --no-deps --no-build --force-recreate romm-webstation
docker compose --env-file .env ps romm-webstation
```

The production marker is already indexed. On a new deployment, run a **Quick
scan** for Wii in RomM as an administrator. Then:

1. Confirm two entries exist: the unchanged **Mario Kart Wii** RVZ and the new
   **Mario Kart Wii - Retro Rewind** DOL marker.
2. If metadata matched an unrelated title, edit only the marker entry's title
   and artwork to **Mario Kart Wii: Retro Rewind**. Do not rename or replace the
   marker file.
3. Connect both controllers, launch the Retro Rewind entry, create/select a
   license, run a two-player race, then use RomM's normal Save & Quit.
4. Confirm RomM reports a newer save timestamp for the Retro Rewind entry and
   that reopening it restores the license. Launch vanilla Mario Kart once and
   verify its existing license/progress remains unchanged.

No RomM container recreation, database migration, Tailscale change, public
port, image rebuild, or global Dolphin update is required.

## Troubleshooting

`Retro Rewind descriptor is unavailable or invalid`
: Run `./scripts/retro_rewind.py status --online`, verify
  `RETRO_REWIND_INSTALL_ROOT` is mounted read-only at
  `/config/retro-rewind`, and recreate WebStation after merging the branch.

The new item does not appear
: The marker is intentionally not inserted directly into MariaDB. Run a Wii
  quick scan in RomM. The file must remain under the existing Wii library.

Both pads control player 1
: Confirm the running container uses the custom image, close the stream,
  connect both pads before reopening it, and run the SDL
  probe. The launch log must contain `GCPad1 ... SDL/0` and
  `GCPad2 ... SDL/1`; do not configure physical Wii Remote passthrough.

A Player invite connects but its controller does nothing
: In the host's Selkies people panel, confirm Gamepad 2 is shown on the guest
  tile. With an older running image, drag the **Gamepad 2** icon onto that tile.
  Recreate WebStation with the custom image after the current session ends to
  enable automatic assignment on future Player invites. Spectator invites are
  intentionally never assigned a gamepad.

Progress is missing after Save & Quit
: Check that `current/riivolution/save` is a symlink to the configured
  `RETRO_REWIND_SAVE_ROOT`, then inspect the Retro Rewind RomM save archive.
  Do not copy vanilla `rksys.dat` into the mod tree.

Vulkan fails or frame pacing is poor
: Set `RETRO_REWIND_VIDEO_BACKEND=OGL` and/or
  `RETRO_REWIND_INTERNAL_RESOLUTION=2` in `.env`, recreate only WebStation, and
  retest. These settings affect only the marker launch.

First launch pauses before showing the game
: Cached/ubershader compilation is intentional. Subsequent launches reuse the
  persistent Dolphin shader cache below `/srv/emulator/webstation`.
