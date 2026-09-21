# Emulator

Private, browser-based retro gaming service for a Tailscale network. It deploys [RomM](https://romm.app/) with its built-in EmulatorJS player, reads ROMs from a CIFS-mounted Corsair NAS, and writes RomM's server-side game assets back to that NAS.

The design deliberately keeps emulation in the browser. The server manages the library, metadata, saves, save states, and backups; it never streams emulator video.

## What is included

- RomM + MariaDB deployment with local database, cache, and resources.
- Immutable-by-default ROM mount and NAS mount guard. RomM will not start if `/mnt/games` is not a CIFS mount from the expected share or lacks the NAS marker.
- RomM `auto_save_sync`, so EmulatorJS uploads native save changes after the game writes them instead of only at Save & Quit.
- A rolling, timestamped NAS snapshot job for RomM assets (20 snapshots by default).
- Tailscale Serve guidance that exposes HTTPS only to the tailnet; the container listens on `127.0.0.1` only.
- Setup, operating, recovery, and ROM-library documentation.

## Quick start

1. On the application host, install Docker Engine with the Compose plugin, Tailscale, `cifs-utils`, `rsync`, and `curl`.
2. Follow [the storage setup](docs/setup.md#1-mount-the-corsair-share) to mount the NAS and add its marker file.
3. Copy `.env.example` to `.env`, fill in your tailnet URL, the NAS server/share values, and generated secrets.
4. Run `scripts/preflight.sh`; it fails closed if storage is not the expected NAS mount.
5. Start the stack with `docker compose --env-file .env up -d`.
6. Configure the tailnet-only HTTPS proxy: `tailscale serve 8080`, then use the URL printed by Tailscale as `ROMM_BASE_URL`.
7. Open that URL over Tailscale, complete RomM's first-user wizard, and scan the library.

Do not run Tailscale Funnel and do not change the Compose port binding to `0.0.0.0`.

## Key paths

| Data | Location | Durability |
| --- | --- | --- |
| ROM library | `/mnt/sophia/games/<platform>` → `/romm/library/roms/<platform>` | Corsair NAS, mounted read-only in RomM |
| RomM assets: native saves, states, screenshots | `/mnt/sophia/games/saves/romm-assets` | Corsair NAS |
| Asset snapshots | `/mnt/sophia/games/backups/romm-assets` | Corsair NAS |
| MariaDB, RomM resources, Redis data | `/srv/emulator` | local app host; back up separately |

RomM stores saves and states together under its own per-user/per-ROM asset tree. This is an intentional adaptation of the PRD's separate `saves/` and `states/` directories: RomM needs one asset root to reliably associate both asset types with the user and ROM. The whole asset tree is still on the NAS and included in the save backup snapshots.

## Operations

- Verify everything: `scripts/health-check.sh`
- Snapshot saves: `scripts/backup-saves.sh`
- Read the recovery procedure: [docs/recovery.md](docs/recovery.md)
- Review known persistence limits: [docs/architecture.md](docs/architecture.md#save-guarantees-and-limits)

Pin `ROMM_IMAGE` to a tested image digest before production upgrades; `latest` is the upstream quick-start default, not an immutable release pin.
