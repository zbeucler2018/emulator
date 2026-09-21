# Adding ROMs

Copy new files into the Corsair NAS under `games/<platform>/`. The deployed layout is:

```text
games/
  gba/
    Example Game (USA).gba
  snes/
    Example Game (USA).sfc
```

Keep the original No-Intro collection intact. Do not rename, delete, or flatten variants merely to simplify the UI. Compose mounts the NAS share at RomM's standard `/romm/library/roms` path, so the existing `games/<platform>/<game>` filesystem is scanned as `roms/<platform>/<game>` without moving files. `config/config.yml` maps this library's `GBA`, `N64`, `NDS`, `NES`, `GameCube`, and `PS2` directory names to RomM platform slugs without moving files.

After copying ROMs, trigger a RomM library scan in the UI. The ROM mount is read-only, so scanning cannot modify the collection. Configure at least one metadata provider in `.env` before the first large scan for richer covers and descriptions.

For firmware a core requires, use RomM's Firmware area rather than placing BIOS files beside ordinary ROMs. Keep legal ownership and applicable law in mind for every ROM and firmware image.
