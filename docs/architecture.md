# Architecture

```text
iPhone, iPad, or desktop browser
            |
            | tailnet-only HTTPS (Tailscale Serve)
            v
Ubuntu application host
  ├─ RomM + built-in EmulatorJS (Docker)
  ├─ MariaDB / Redis-compatible cache (local disk)
  └─ ext4 game disk: /mnt/games/Sophia/games
                   ├─ <platform>/         (read-only to RomM)
                   ├─ saves/romm-assets/ (RomM saves + states)
                   └─ backups/romm-assets/snapshots/
```

## Responsibilities and trust boundaries

RomM scans and presents the ROM library, keeps metadata locally, and runs EmulatorJS in the user's browser. The browser downloads the ROM and executes WebAssembly locally; application-host CPU is not used for frame rendering.

The dedicated game disk is the canonical store for ROMs and player progress. The application host's system disk owns only replaceable state: database rows, downloaded artwork, and Redis-compatible task data. No database directory is placed in the game library.

The RomM container has a read-only ROM mount. It can write only to its assets mount, which points to `games/saves/romm-assets` on the game disk. This asset root contains RomM's per-user/per-ROM saves, save states, and associated screenshots.

## Storage safety

`scripts/mount-check.sh` verifies all of the following before the stack starts:

- `/mnt/games/Sophia/games` exists on the configured `ext4` game disk.
- `saves/romm-assets/` exists beneath it.
- a manually-created `.emulator-nas-marker` file exists at its root.

The Compose `mount-guard` repeats the check as a mandatory dependency. The host-side preflight is authoritative because it can inspect the backing filesystem directly. This prevents a missing disk from becoming an empty directory on the system disk that silently accepts writes.

## Save guarantees and limits

RomM's EmulatorJS integration stores native saves and save states on the server. With `emulatorjs.auto_save_sync: true`, each emulator save-file write is uploaded instead of waiting for Save & Quit. Save states are uploaded when explicitly created.

This substantially reduces loss risk from closing a tab, but it cannot make a browser crash, iOS background termination, or dropped network connection transactional. The browser must first observe the game's write, then upload it. Keep the browser open until its save-sync status returns, and prefer native in-game saves as the primary durable record. Save states are secondary and core/version-specific; keep a stable core per platform if you depend on them.

If connectivity drops, the browser cache may temporarily contain newer state than the server. Treat the server's visible save-sync timestamp and the game-disk backup as the durability signal, not local browser storage.

Webstation's Dolphin broker deliberately clears `StateSaves`, `GC`, and `Wii`
at every game activation, before restoring the selected RomM save archive.
This prevents one user's per-game saves leaking into another session, but a
Wii Mii database is console-wide rather than game-specific. The Dolphin
launcher therefore hard-links `Wii/shared2/menu/FaceLib/RFL_DB.dat` to
`/config/.romm-shared/dolphin-wii/RFL_DB.dat`, outside the cleared tree. The
broker continues to clear and sync every other Wii save normally. Do not set a
`clears_stale_saves` override in RomM for this deployment: Webstation broker
0.9.0 already declares and performs the clear, and the wrapper preserves only
the shared Mii database.

The Infinity Blade backend follows the same broker isolation contract. Wine's
runtime and registry persist below `/config/infinity-blade/prefix`, while the
broker clears/restores only `drive_c/users/abc/Documents/My Games` for the
selected RomM user and game. This keeps the DirectX/VC++ setup local and avoids
shipping an entire Wine prefix in every save archive.

## Platform baseline

The supplied config selects a conservative core for GB/GBC/GBA, NES, SNES, N64, Master System, Game Gear, and Genesis. RomM/EmulatorJS also has support for the optional Neo Geo Pocket and WonderSwan families. N64 results vary by device and game; it is intentionally the Phase 1 ceiling. Nintendo DS and disc-based platforms are out of scope.

RomM calculates ROM hashes during scans and uses metadata provider priorities. Region preference is USA, Europe, World, Japan; ROM region tags take precedence when present. All No-Intro variants stay untouched on disk.
