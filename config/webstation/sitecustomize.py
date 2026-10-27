"""Small, deployment-local WebStation broker extensions."""

from __future__ import annotations

import os


if os.environ.get("ROMM_RPC3_SKATE3_SAVE_FILTER") == "true":
    from webstation_broker.emulators import rpcs3

    # Broker 0.15.2+ stopped exporting installed RPCS3 game-data directories
    # as saves upstream, so its old private helper no longer exists. Retain
    # the compatibility filter only for older broker images; importantly, do
    # not abort the rest of this module (including Infinity Blade registration)
    # on current releases.
    _original_gamedata_dirs = getattr(rpcs3, "_gamedata_dirs", None)

    if _original_gamedata_dirs is not None:

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
