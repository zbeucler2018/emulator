"""Scoped WebStation broker override for Skate 3's RPCS3 install data.

Skate 3 stores required installed content in ``game/BLUS30464_INSTALL``. The
generic RPCS3 broker classifies that non-bootable directory as CellGameData,
which makes every save export include about 1.2 GiB of game files. Keep the
real CellSaveData save directory eligible, but never export or clear this
installed-content directory.

Loaded as ``sitecustomize`` only in the WebStation container.
"""

from __future__ import annotations

import os


if os.environ.get("ROMM_RPC3_SKATE3_SAVE_FILTER") == "true":
    from webstation_broker.emulators import rpcs3

    _original_gamedata_dirs = rpcs3._gamedata_dirs

    def _gamedata_dirs_without_skate3_install():
        return [
            path
            for path in _original_gamedata_dirs()
            if path.name != "BLUS30464_INSTALL"
        ]

    rpcs3._gamedata_dirs = _gamedata_dirs_without_skate3_install
