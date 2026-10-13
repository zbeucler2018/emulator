"""Small, deployment-local WebStation broker extensions."""

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


if os.environ.get("INFINITY_BLADE_ENABLED") == "true":
    from webstation_broker.emulators import REGISTRY
    from infinity_blade import InfinityBlade

    REGISTRY[InfinityBlade.name] = InfinityBlade
