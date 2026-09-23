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

## PS3 installed games

PS3 games installed as `PS3/<category>/<serial>/` commonly have a serial-number
directory name, while their human-readable title is stored in that game's
`PARAM.SFO`. RomM's public metadata providers do not reliably resolve those
directories. Generate RomM's local metadata sidecar instead:

```bash
python3 scripts/generate-ps3-gamelist.py /mnt/sophia/games/PS3 --dry-run
python3 scripts/generate-ps3-gamelist.py /mnt/sophia/games/PS3
```

This creates only `PS3/gamelist.xml`; it never moves, renames, extracts, or
edits game files. It lists only folder titles with an `EBOOT.BIN` in a supported
digital-install or disc-dump layout, so DLC and game-data folders that merely
have a `PARAM.SFO` do not become unlaunchable RomM entries. Review the dry-run
output first. For future refreshes, use `--force` only after reviewing the
generated titles, then run a PS3 library scan with the local `gamelist`
metadata source enabled.

For firmware a core requires, use RomM's Firmware area rather than placing BIOS files beside ordinary ROMs. Keep legal ownership and applicable law in mind for every ROM and firmware image.
