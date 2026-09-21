# Architecture

```text
iPhone, iPad, or desktop browser
            |
            | tailnet-only HTTPS (Tailscale Serve)
            v
Ubuntu application host
  ├─ RomM + built-in EmulatorJS (Docker)
  ├─ MariaDB / Redis-compatible cache (local disk)
  └─ CIFS mount: /mnt/games
                └─ Corsair NAS
                   ├─ roms/              (read-only to RomM)
                   ├─ saves/romm-assets/ (RomM saves + states)
                   └─ backups/romm-assets/snapshots/
```

## Responsibilities and trust boundaries

RomM scans and presents the ROM library, keeps metadata locally, and runs EmulatorJS in the user's browser. The browser downloads the ROM and executes WebAssembly locally; application-host CPU is not used for frame rendering.

The NAS is the canonical store for ROMs and player progress. The local application host owns only replaceable state: database rows, downloaded artwork, and Redis-compatible task data. No database directory is placed on CIFS/SMB.

The RomM container has a read-only ROM mount. It can write only to its assets mount, which points to `games/saves/romm-assets` on the NAS. This asset root contains RomM's per-user/per-ROM saves, save states, and associated screenshots.

## Storage safety

`scripts/mount-check.sh` verifies all of the following before the stack starts:

- `/mnt/games` exists and is a `cifs` filesystem from the configured Corsair share.
- `roms/` and `saves/romm-assets/` exist beneath it.
- a manually-created `.emulator-nas-marker` file exists at its root.

The Compose `mount-guard` repeats a reduced check as a mandatory dependency. The host-side preflight is the authoritative check because it can inspect the CIFS source directly. This prevents a failed mount from becoming an empty local directory that silently accepts writes.

## Save guarantees and limits

RomM's EmulatorJS integration stores native saves and save states on the server. With `emulatorjs.auto_save_sync: true`, each emulator save-file write is uploaded instead of waiting for Save & Quit. Save states are uploaded when explicitly created.

This substantially reduces loss risk from closing a tab, but it cannot make a browser crash, iOS background termination, or dropped network connection transactional. The browser must first observe the game's write, then upload it. Keep the browser open until its save-sync status returns, and prefer native in-game saves as the primary durable record. Save states are secondary and core/version-specific; keep a stable core per platform if you depend on them.

If connectivity drops, the browser cache may temporarily contain newer state than the server. Treat the server's visible save-sync timestamp and the NAS backup as the durability signal, not local browser storage.

## Platform baseline

The supplied config selects a conservative core for GB/GBC/GBA, NES, SNES, N64, Master System, Game Gear, and Genesis. RomM/EmulatorJS also has support for the optional Neo Geo Pocket and WonderSwan families. N64 results vary by device and game; it is intentionally the Phase 1 ceiling. Nintendo DS and disc-based platforms are out of scope.

RomM calculates ROM hashes during scans and uses metadata provider priorities. Region preference is USA, Europe, World, Japan; ROM region tags take precedence when present. All No-Intro variants stay untouched on disk.
