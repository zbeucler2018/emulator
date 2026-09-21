# Adding ROMs

Copy new files into the Corsair NAS under `games/roms/<platform>/`. RomM's default layout is:

```text
roms/
  gba/
    Example Game (USA).gba
  snes/
    Example Game (USA).sfc
```

Keep the original No-Intro collection intact. Do not rename, delete, or flatten variants merely to simplify the UI. RomM scans hashes and metadata, while the configured region preference helps choose a representative result. The Compose stack mounts the configured ROM-library directory directly as RomM's library root, so platform folders begin immediately beneath it. `config/config.yml` maps this library's `GBA`, `N64`, `NDS`, `NES`, `GameCube`, and `PS2` directory names to RomM platform slugs without moving files.

After copying ROMs, trigger a RomM library scan in the UI. The ROM mount is read-only, so scanning cannot modify the collection. Configure at least one metadata provider in `.env` before the first large scan for richer covers and descriptions.

For firmware a core requires, use RomM's Firmware area rather than placing BIOS files beside ordinary ROMs. Keep legal ownership and applicable law in mind for every ROM and firmware image.
