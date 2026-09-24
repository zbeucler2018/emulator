"""Webstation startup hook for RPCS3 installed titles in the ROM library.

RPCS3 accepts installed titles only below its own dev_hdd0/game tree. Docker
bind-mounts the read-only PS3/digital_games library at that path, so the broker
uses the installed-title route while preserving the one canonical game copy.
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
        # RPCS3's command-line loader treats an EBOOT.BIN argument as a disc
        # boot, even when it lives inside dev_hdd0/game. Installed digital
        # titles must instead be passed as their title-directory.
        installed_title = GAME_DIR / path.name
        return installed_title if (installed_title / "USRDIR" / "EBOOT.BIN").is_file() else boot

    Rpcs3.resolve_rom_file = resolve_rom_file
except Exception:
    # A Webstation image without the RPCS3 broker must still be able to start.
    pass
