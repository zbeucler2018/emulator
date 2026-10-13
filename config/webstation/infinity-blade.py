"""Infinity Blade I-III launcher for the WebStation broker.

This is intentionally game-specific. It accepts only the three known
Infinity Blade directory names and their documented executable layouts; it is
not an arbitrary Windows executable launcher.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

from webstation_broker.emulators.base import Emulator, base_launch_env


ROM_ROOT = Path(os.environ.get("ROM_ROOT", "/romm/library"))
PREFIX_DIR = Path(
    os.environ.get("INFINITY_BLADE_WINEPREFIX", "/config/infinity-blade/prefix")
)
WINE_USER = os.environ.get("INFINITY_BLADE_WINE_USER", "abc")
MY_GAMES_SUBTREE = f"users/{WINE_USER}/Documents/My Games"
RUNTIME_MARKER = PREFIX_DIR / ".infinity-blade-runtime-ready"
LAUNCH_WRAPPER = os.environ.get(
    "INFINITY_BLADE_LAUNCH_WRAPPER", "/opt/romm/bin/infinity-blade-wine"
)


@dataclass(frozen=True)
class Game:
    key: str
    names: tuple[str, ...]
    executables: tuple[str, ...]
    override_env: str


GAMES = (
    Game(
        "ib1",
        ("infinity blade", "infinity blade i", "infinity blade 1", "infinity blade pc"),
        (
            "Binaries/Win64/IB1.exe",
            "Binaries/Infinity Blade Launcher.exe",
            # The original release announcement spells the file this way.
            "Binaries/Infinity Blade laucher.exe",
        ),
        "INFINITY_BLADE_IB1_EXE",
    ),
    Game(
        "ib2",
        ("infinity blade ii", "infinity blade 2"),
        (
            "Binaries/Win32/IB2.exe",
            "Binaries/Win64/IB2.exe",
            "Binaries/Infinity Blade Launcher.exe",
        ),
        "INFINITY_BLADE_IB2_EXE",
    ),
    Game(
        "ib3",
        ("infinity blade iii", "infinity blade 3"),
        (
            "Binaries/Infinity Blade III.exe",
            "Infinity Blade III.exe",
            "Binaries/Win64/IB3.exe",
            "Binaries/Win32/IB3.exe",
            "IB3.exe",
        ),
        "INFINITY_BLADE_IB3_EXE",
    ),
)


def _normalise_name(value: str) -> str:
    value = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", value.casefold())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def _safe_override(value: str) -> Optional[str]:
    """Return a safe relative POSIX path, or None for an unsafe override."""
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        return None
    return path.as_posix()


def _casefold_path(root: Path, relative: str) -> Optional[Path]:
    """Resolve ``relative`` under ``root`` without assuming Windows casing."""
    current = root
    for wanted in PurePosixPath(relative).parts:
        try:
            matches = [
                entry
                for entry in current.iterdir()
                if entry.name.casefold() == wanted.casefold()
            ]
        except OSError:
            return None
        if len(matches) != 1:
            return None
        current = matches[0]
    try:
        resolved = current.resolve()
        root_resolved = root.resolve()
    except OSError:
        return None
    return resolved if resolved.is_file() and resolved.is_relative_to(root_resolved) else None


def _game_for_root(root: Path) -> Optional[Game]:
    normalised = _normalise_name(root.name)
    exact = [game for game in GAMES if normalised in game.names]
    if len(exact) == 1:
        return exact[0]

    # Versioned directory names are common. Resolve an unambiguous numeral,
    # treating a bare "Infinity Blade" as the first game.
    if normalised.startswith("infinity blade"):
        suffix = normalised.removeprefix("infinity blade").strip()
        if suffix.startswith(("iii", "3")):
            return GAMES[2]
        if suffix.startswith(("ii", "2")):
            return GAMES[1]
        if not suffix or suffix.startswith(("i", "1", "pc")):
            return GAMES[0]
    return None


def resolve_game(path: Path) -> tuple[Optional[Game], Optional[Path]]:
    """Resolve a RomM folder/file to one known game and executable."""
    start = path.parent if path.is_file() else path
    try:
        rom_root = ROM_ROOT.resolve()
        start = start.resolve()
    except OSError:
        return None, None
    if not start.is_relative_to(rom_root):
        return None, None

    roots = [start]
    for parent in start.parents:
        if parent == rom_root:
            break
        roots.append(parent)
    for root in roots:
        game = _game_for_root(root)
        if game is None:
            continue
        candidates = list(game.executables)
        override = os.environ.get(game.override_env)
        if override:
            safe = _safe_override(override)
            if safe is None:
                return game, None
            candidates.insert(0, safe)
        for candidate in candidates:
            executable = _casefold_path(root, candidate)
            if executable is not None:
                return game, executable
        return game, None
    return None, None


class InfinityBlade(Emulator):
    """Launch only the three Infinity Blade PC ports through Wine."""

    name = "infinity-blade"
    display_name = "Wine"
    rom_extensions = (".exe",)
    save_root = PREFIX_DIR / "drive_c"
    save_subtrees = (MY_GAMES_SUBTREE,)
    clears_stale_saves = True
    log_path = Path("/config/infinity-blade/wine.log")
    term_timeout = float(os.environ.get("INFINITY_BLADE_STOP_WAIT", "20"))

    def __init__(self) -> None:
        super().__init__()
        self._game: Optional[Game] = None

    def resolve_rom_file(self, path: Path) -> Optional[Path]:
        self._game, executable = resolve_game(path)
        return executable

    def clear_working_slot(self, excluded: tuple[str, ...] = ()) -> None:
        self._clear_save_subtrees(excluded)

    def prepare_restore(self) -> None:
        (self.save_root / MY_GAMES_SUBTREE).mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def launch(self, rom_path: Optional[Path], resume_slot: Optional[int]) -> None:
        del resume_slot
        if self._game is None or rom_path is None:
            raise RuntimeError("Infinity Blade game and executable were not resolved")
        if not RUNTIME_MARKER.is_file():
            raise RuntimeError(
                "Infinity Blade Wine runtime is not initialized; run "
                "scripts/setup-infinity-blade.sh"
            )

        env = base_launch_env()
        env["WINEPREFIX"] = str(PREFIX_DIR)
        env["WINEARCH"] = "win64"
        env.setdefault("WINEDEBUG", "-all")
        env["INFINITY_BLADE_GAME"] = self._game.key
        self._spawn([LAUNCH_WRAPPER, str(rom_path)], env)
