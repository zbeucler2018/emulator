# Emulator

Private retro gaming service for a Tailscale network. It deploys [RomM](https://romm.app/) with its built-in EmulatorJS player and a Webstation native-emulator streaming service, reads ROMs from a dedicated local game disk, and writes RomM's server-side game assets back to that disk.

Older systems continue to run in the browser through EmulatorJS. Webstation streams native emulators for supported heavier systems such as GameCube and PS2, while RomM remains the single frontend.

## What is included

- RomM + MariaDB deployment with local database, cache, and resources.
- Immutable-by-default ROM mount and storage guard. RomM will not start if the configured ext4 game disk or its marker is absent.
- RomM `auto_save_sync`, so EmulatorJS uploads native save changes after the game writes them instead of only at Save & Quit.
- A rolling, timestamped snapshot job for RomM assets (20 snapshots by default).
- Tailscale Serve guidance that exposes HTTPS only to the tailnet; the container listens on `127.0.0.1` only.
- A path-preserving Tailscale Serve route for Webstation at `/streaming/`.
- RomM-admin desktop sessions over that same authenticated `/streaming/`
  route; Webstation's standalone port 3001 stays unpublished.
- A shared Dolphin Wii Mii database that survives per-game save cleanup while
  leaving normal RomM Wii save syncing enabled.
- A direct-launch Retro Rewind integration with atomic official-pack updates,
  isolated RomM saves, and two indexed browser gamepads.
- A scoped Infinity Blade I-III Wine backend using the existing WebStation and
  Selkies stream; game files remain user-supplied.
- Setup, operating, recovery, and ROM-library documentation.

## Quick start

1. On the application host, install Docker Engine with the Compose plugin, Tailscale, `rsync`, and `curl`.
2. Mount the game disk at `/mnt/games` and retain the marker at `/mnt/games/Sophia/games/.emulator-nas-marker`.
3. Copy `.env.example` to `.env`, fill in your tailnet URL and generated secrets.
4. Run `scripts/preflight.sh`; it fails closed if storage is not the expected ext4 mount.
5. Start the stack with `docker compose --env-file .env up -d`.
6. Configure the tailnet-only HTTPS proxy for both RomM and Webstation as described in [the Tailscale section](docs/setup.md#3-publish-only-inside-tailscale), then use the root URL as `ROMM_BASE_URL`.
7. Open that URL over Tailscale, complete RomM's first-user wizard, and scan the library.

Do not run Tailscale Funnel and do not change the Compose port binding to `0.0.0.0`.

## Key paths

| Data | Location | Durability |
| --- | --- | --- |
| ROM library | `/mnt/games/Sophia/games/<platform>` → `/romm/library/roms/<platform>` | local ext4 game disk, mounted read-only in RomM |
| RomM assets: native saves, states, screenshots | `/mnt/games/Sophia/games/saves/romm-assets` | local game disk |
| Asset snapshots | `/mnt/games/Sophia/games/backups/romm-assets` | local game disk |
| MariaDB, RomM resources, Redis data | `/srv/emulator` | local app host; back up separately |
| Webstation emulator configuration, firmware, and stream state | `/srv/emulator/webstation` | local app host; back up separately |
| Versioned Retro Rewind assets and descriptor | `/srv/emulator/retro-rewind` | local app host; read-only in WebStation |
| Shared Dolphin Wii Mii database | `/srv/emulator/webstation/.romm-shared/dolphin-wii/RFL_DB.dat` | local app host; shared by Wii games |

RomM stores saves and states together under its own per-user/per-ROM asset tree. This is an intentional adaptation of the PRD's separate `saves/` and `states/` directories: RomM needs one asset root to reliably associate both asset types with the user and ROM. The whole asset tree remains on the game disk and is included in the save backup snapshots.

To configure emulators without launching a game, sign in as a RomM admin and
open **Administration → Emulator Streaming** (direct path:
`/administration?tab=streaming`). Select **Desktop** for **Emulation station**.
RomM claims the container and opens `/stream/desktop`, which uses the existing
tailnet-only `/streaming/` route. Open the **Dolphin Emulator** desktop icon to
configure Dolphin or create Miis. Release the desktop session in RomM when done.

## Operations

- Verify everything: `scripts/health-check.sh`
- Snapshot saves: `scripts/backup-saves.sh`
- Read the recovery procedure: [docs/recovery.md](docs/recovery.md)
- Review known persistence limits: [docs/architecture.md](docs/architecture.md#save-guarantees-and-limits)

Pin `ROMM_IMAGE` to a tested image digest before production upgrades; `latest` is the upstream quick-start default, not an immutable release pin.

Infinity Blade has a separate, game-specific setup because its community PC
ports are not included: [Infinity Blade through RomM](docs/infinity-blade.md).

Mario Kart Wii: Retro Rewind installation, activation, controllers, saves, and
rollback are documented in [docs/retro-rewind.md](docs/retro-rewind.md).
