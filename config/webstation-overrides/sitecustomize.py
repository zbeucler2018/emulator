"""Webstation startup hook for ROM-library copies of RPCS3 installed titles.

RPCS3 accepts installed titles only below its own dev_hdd0/game tree. The
library keeps those titles read-only under PS3/digital_games, so persistent
host-side symlinks expose them at the required path without a second copy.
"""

from pathlib import Path


try:
    from webstation_broker.emulators.rpcs3 import GAME_DIR, Rpcs3

    _resolve_rom_file = Rpcs3.resolve_rom_file

    def resolve_rom_file(self: Rpcs3, path: Path) -> Path | None:
        boot = _resolve_rom_file(self, path)
        # Only redirect a library folder that uses RPCS3's installed-title
        # layout. Disc rips (PS3_GAME/USRDIR/EBOOT.BIN) keep the broker's
        # upstream launch behavior.
        if boot is None or not path.is_dir() or not (path / "USRDIR" / "EBOOT.BIN").is_file():
            return boot
        alias = GAME_DIR / path.name / "USRDIR" / "EBOOT.BIN"
        return alias if alias.is_file() else boot

    Rpcs3.resolve_rom_file = resolve_rom_file
except Exception:
    # A Webstation image without the RPCS3 broker must still be able to start.
    pass
