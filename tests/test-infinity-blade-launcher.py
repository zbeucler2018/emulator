#!/usr/bin/env python3
"""Focused tests for the local Infinity Blade broker launcher."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


class StubEmulator:
    def __init__(self) -> None:
        self._proc = None

    def _clear_save_subtrees(self, excluded=()):
        del excluded


base = types.ModuleType("webstation_broker.emulators.base")
base.Emulator = StubEmulator
base.base_launch_env = lambda: {}
sys.modules["webstation_broker"] = types.ModuleType("webstation_broker")
sys.modules["webstation_broker.emulators"] = types.ModuleType(
    "webstation_broker.emulators"
)
sys.modules["webstation_broker.emulators.base"] = base

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "config/webstation/infinity-blade.py"
)


class LauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.rom_root = Path(cls.tmp.name) / "library"
        cls.rom_root.mkdir()
        os.environ["ROM_ROOT"] = str(cls.rom_root)
        spec = importlib.util.spec_from_file_location("infinity_blade", MODULE_PATH)
        assert spec and spec.loader
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def make_exe(self, game_dir: str, relative: str) -> Path:
        path = self.rom_root / game_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return path.resolve()

    def test_ib1_direct_executable_is_preferred(self) -> None:
        direct = self.make_exe("Infinity Blade", "Binaries/Win64/IB1.exe")
        self.make_exe("Infinity Blade", "Binaries/Infinity Blade Launcher.exe")
        game, executable = self.module.resolve_game(self.rom_root / "Infinity Blade")
        self.assertEqual(game.key, "ib1")
        self.assertEqual(executable, direct)

    def test_ib2_win32_layout(self) -> None:
        direct = self.make_exe("Infinity Blade II", "Binaries/Win32/IB2.exe")
        game, executable = self.module.resolve_game(self.rom_root / "Infinity Blade II")
        self.assertEqual(game.key, "ib2")
        self.assertEqual(executable, direct)

    def test_ib3_wrapper_layout_is_case_insensitive(self) -> None:
        wrapper = self.make_exe("Infinity Blade III", "binaries/infinity blade iii.EXE")
        game, executable = self.module.resolve_game(self.rom_root / "Infinity Blade III")
        self.assertEqual(game.key, "ib3")
        self.assertEqual(executable, wrapper)

    def test_rejects_non_infinity_blade_game(self) -> None:
        self.make_exe("Other Game", "Binaries/Win64/IB1.exe")
        game, executable = self.module.resolve_game(self.rom_root / "Other Game")
        self.assertIsNone(game)
        self.assertIsNone(executable)

    def test_rejects_unsafe_override(self) -> None:
        root = self.rom_root / "Infinity Blade II"
        root.mkdir(exist_ok=True)
        os.environ["INFINITY_BLADE_IB2_EXE"] = "../../outside.exe"
        try:
            game, executable = self.module.resolve_game(root)
        finally:
            os.environ.pop("INFINITY_BLADE_IB2_EXE", None)
        self.assertEqual(game.key, "ib2")
        self.assertIsNone(executable)


if __name__ == "__main__":
    unittest.main()
