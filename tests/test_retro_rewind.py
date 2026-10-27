#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves forward annotations through sys.modules.
    import sys

    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rr = load_module("retro_rewind", ROOT / "scripts" / "retro_rewind.py")
wrapper = load_module(
    "dolphin_retro_rewind_wrapper", ROOT / "scripts" / "dolphin-retro-rewind-wrapper.py"
)


def write_iso(path: Path, game_id: bytes = b"RMCE01", revision: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(game_id + b"\0" + bytes([revision]) + b"mock-disc")


def write_pack(path: Path, version: str, *, include_code: bool = True) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("RetroRewind6/version.txt", version)
        archive.writestr(
            "riivolution/RetroRewind6.xml",
            '<wiidisc version="1"><options><section name="Retro Rewind"/></options></wiidisc>',
        )
        if include_code:
            archive.writestr("RetroRewind6/Binaries/Code.pul", b"p" * 100_001)
            archive.writestr("RetroRewind6/Binaries/Loader.pul", b"loader")
        for directory in ("Tracks", "CT/Tracks", "Character", "strm", "Assets", "Language"):
            archive.writestr(f"RetroRewind6/{directory}/fixture.bin", b"fixture")


def install_args(root: Path, library: Path, archive: Path, version: str) -> argparse.Namespace:
    return argparse.Namespace(
        rom_library=library,
        install_root=root,
        container_library=Path("/romm/library/roms"),
        container_root=Path("/config/retro-rewind"),
        container_save_root=Path("/config/.local/share/dolphin-emu/Wii/riivolution-save"),
        container="unused-test-container",
        rom=None,
        dolphin_tool=None,
        archive=archive,
        version=version,
        sha256=None,
        dry_run=False,
    )


class RomValidationTests(unittest.TestCase):
    def test_iso_region_revision_and_container_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary) / "library with spaces & punctuation"
            rom = library / "Wii" / "Mario Kart Wii (USA) [!].iso"
            write_iso(rom)
            info = rr.inspect_rom(
                rom, library, Path("/romm/library/roms"), "unused", None
            )
            self.assertEqual(info.game_id, "RMCE01")
            self.assertEqual(info.revision, 0)
            self.assertEqual(info.container_path, "/romm/library/roms/Wii/Mario Kart Wii (USA) [!].iso")

    def test_wbfs_header_offset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary)
            rom = library / "Wii" / "Mario Kart Wii.wbfs"
            rom.parent.mkdir(parents=True)
            rom.write_bytes(b"\0" * 0x200 + b"RMCP01" + b"\0\0" + b"mock")
            info = rr.inspect_rom(rom, library, Path("/games"), "unused", None)
            self.assertEqual((info.game_id, info.revision), ("RMCP01", 0))

    def test_compressed_format_uses_dolphin_header(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary)
            rom = library / "Wii" / "Mario Kart Wii.rvz"
            rom.parent.mkdir(parents=True)
            rom.write_bytes(b"mock-rvz")
            completed = mock.Mock(
                stdout=json.dumps(
                    {"game_id": "RMCJ01", "revision": 0, "region": "NTSC-J"}
                )
            )
            with mock.patch.object(rr.subprocess, "run", return_value=completed) as run:
                info = rr.inspect_rom(
                    rom, library, Path("/romm/library/roms"), "webstation", None
                )
            self.assertEqual(info.game_id, "RMCJ01")
            self.assertIn("/romm/library/roms/Wii/Mario Kart Wii.rvz", run.call_args.args[0])

    def test_rejects_wrong_game_region_and_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary)
            wrong_game = library / "Wii" / "Mario Kart Wii.iso"
            write_iso(wrong_game, b"RSBE01")
            with self.assertRaisesRegex(rr.RetroRewindError, "not a supported"):
                rr.inspect_rom(wrong_game, library, Path("/games"), "unused")
            write_iso(wrong_game, b"RMCE01", revision=1)
            with self.assertRaisesRegex(rr.RetroRewindError, "revision 1"):
                rr.inspect_rom(wrong_game, library, Path("/games"), "unused")

    def test_rejects_unsupported_format(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary)
            rom = library / "Wii" / "Mario Kart Wii.zip"
            rom.parent.mkdir(parents=True)
            rom.write_bytes(b"not-a-rom")
            with self.assertRaisesRegex(rr.RetroRewindError, "unsupported"):
                rr.inspect_rom(rom, library, Path("/games"), "unused")


class AssetTests(unittest.TestCase):
    def test_missing_and_corrupt_assets_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "RetroRewind6").mkdir()
            (root / "RetroRewind6" / "version.txt").write_text("6.13.4")
            with self.assertRaisesRegex(rr.RetroRewindError, "missing"):
                rr.validate_release(root)

            archive = root / "bad.zip"
            archive.write_bytes(b"not a zip")
            with self.assertRaisesRegex(rr.RetroRewindError, "corrupt"):
                rr.extract_archive(archive, root / "output")

    def test_archive_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escaped", "bad")
            with self.assertRaisesRegex(rr.RetroRewindError, "unsafe path"):
                rr.extract_archive(archive_path, Path(temporary) / "output")
            self.assertFalse((Path(temporary) / "escaped").exists())

    def test_descriptor_generation_handles_special_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Retro Rewind & Friends"
            info = rr.RomInfo(
                path="/host/Mario Kart Wii [!].rvz",
                container_path="/romm/library/roms/Wii/Mario Kart Wii [!].rvz",
                format="rvz",
                game_id="RMCE01",
                region="NTSC-U",
                revision=0,
                size=123,
            )
            descriptor_path = rr.write_descriptor(root, Path("/config/Retro Rewind & Friends"), info)
            descriptor = json.loads(descriptor_path.read_text())
            self.assertEqual(descriptor["base-file"], info.container_path)
            self.assertEqual(descriptor["riivolution"]["patches"][0]["options"][0]["choice"], 1)
            self.assertNotIn("Seperate Savegame", descriptor_path.read_text())


class InstallerTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.library = base / "game library"
        write_iso(self.library / "Wii" / "Mario Kart Wii (USA).iso")
        self.install_root = base / "persistent config" / "retro-rewind"
        self.pack1 = base / "pack one.zip"
        self.pack2 = base / "pack two.zip"
        write_pack(self.pack1, "6.13.3")
        write_pack(self.pack2, "6.13.4")
        self.session_patch = mock.patch.object(rr, "_assert_no_game_session")
        self.session_patch.start()
        self.stdout_patch = mock.patch("sys.stdout", new=io.StringIO())
        self.stdout_patch.start()

    def tearDown(self) -> None:
        self.stdout_patch.stop()
        self.session_patch.stop()
        self.temporary.cleanup()

    def test_reexecution_update_and_rollback(self) -> None:
        rr.install(install_args(self.install_root, self.library, self.pack1, "6.13.3"))
        rr.install(install_args(self.install_root, self.library, self.pack1, "6.13.3"))
        self.assertEqual(rr._current_version(self.install_root), "6.13.3")
        self.assertEqual(
            (self.library / "Wii" / rr.MARKER_NAME).read_bytes(), rr.MARKER_CONTENT
        )

        rr.install(install_args(self.install_root, self.library, self.pack2, "6.13.4"))
        self.assertEqual(rr._current_version(self.install_root), "6.13.4")
        self.assertTrue((self.install_root / "releases" / "6.13.3").is_dir())
        save_link = self.install_root / "releases" / "6.13.4" / "riivolution" / "save"
        self.assertTrue(save_link.is_symlink())
        self.assertEqual(
            save_link.readlink(),
            Path("/config/.local/share/dolphin-emu/Wii/riivolution-save"),
        )

        rollback_args = argparse.Namespace(
            install_root=self.install_root,
            container="unused",
            version=None,
            dry_run=False,
        )
        rr.rollback(rollback_args)
        self.assertEqual(rr._current_version(self.install_root), "6.13.3")

    def test_failed_update_keeps_current_release(self) -> None:
        rr.install(install_args(self.install_root, self.library, self.pack1, "6.13.3"))
        bad_pack = Path(self.temporary.name) / "interrupted.zip"
        write_pack(bad_pack, "6.13.4", include_code=False)
        with self.assertRaisesRegex(rr.RetroRewindError, "missing"):
            rr.install(install_args(self.install_root, self.library, bad_pack, "6.13.4"))
        self.assertEqual(rr._current_version(self.install_root), "6.13.3")
        self.assertFalse((self.install_root / "releases" / "6.13.4").exists())

    def test_checksum_mismatch_does_not_publish(self) -> None:
        args = install_args(self.install_root, self.library, self.pack1, "6.13.3")
        args.sha256 = "0" * 64
        with self.assertRaisesRegex(rr.RetroRewindError, "checksum mismatch"):
            rr.install(args)
        self.assertIsNone(rr._current_version(self.install_root))


class LauncherTests(unittest.TestCase):
    def _retro_tree(self, root: Path) -> tuple[dict[str, str], str, str]:
        marker = root / "Mario Kart Wii - Retro Rewind.dol"
        marker.write_bytes(wrapper.MARKER_CONTENT)
        base = root / "Mario Kart Wii (USA) [!].rvz"
        base.write_bytes(b"mock")
        assets = root / "current"
        (assets / "riivolution").mkdir(parents=True)
        save_root = root / "broker Wii tree" / "riivolution-save"
        (assets / "riivolution" / "save").symlink_to(save_root, target_is_directory=True)
        xml = assets / "riivolution" / "RetroRewind6.xml"
        xml.write_text("<wiidisc/>")
        descriptor = root / "Retro Rewind.json"
        descriptor.write_text(
            json.dumps(
                {
                    "base-file": str(base),
                    "type": "dolphin-game-mod-descriptor",
                    "version": 1,
                    "riivolution": {
                        "patches": [{"root": str(assets), "xml": str(xml), "options": []}]
                    },
                }
            )
        )
        env = {
            "DOLPHIN_FINAL_BIN": "/real/dolphin",
            "RETRO_REWIND_MARKER": str(marker),
            "RETRO_REWIND_DESCRIPTOR": str(descriptor),
            "RETRO_REWIND_SAVE_ROOT": str(save_root),
        }
        return env, str(marker), str(descriptor)

    def test_vanilla_and_other_games_are_unchanged(self) -> None:
        argv = ["-b", "-e", "/games/Mario Kart Wii.rvz", "-C", "Dolphin.Core.SlotA=8"]
        command, is_retro = wrapper.build_command(argv, {"DOLPHIN_FINAL_BIN": "/real/dolphin"})
        self.assertFalse(is_retro)
        self.assertEqual(command, ["/real/dolphin", *argv])

    def test_retro_launch_descriptor_graphics_and_two_independent_pads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env, marker, descriptor = self._retro_tree(Path(temporary))
            command, is_retro = wrapper.build_command(["-b", "-e", marker], env)
            self.assertTrue(is_retro)
            self.assertIn(descriptor, command)
            self.assertNotIn(marker, command)
            joined = "\n".join(command)
            self.assertIn("GFX.Settings.InternalResolution=3", joined)
            self.assertIn("GFX.Settings.ShaderCompilationMode=1", joined)
            self.assertIn("Dolphin.Core.SIDevice0=6", joined)
            self.assertIn("Dolphin.Core.SIDevice1=6", joined)
            self.assertIn("GCPad.GCPad1.Device=SDL/0/Xbox 360 Controller", joined)
            self.assertIn("GCPad.GCPad2.Device=SDL/1/Xbox 360 Controller", joined)
            self.assertNotIn("GCPad.GCPad2.Device=SDL/0/", joined)

    def test_missing_assets_fail_before_dolphin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env, marker, descriptor = self._retro_tree(Path(temporary))
            Path(descriptor).unlink()
            with self.assertRaisesRegex(RuntimeError, "descriptor"):
                wrapper.build_command(["--exec", marker], env)


class DeploymentWiringTests(unittest.TestCase):
    def test_compose_mounts_pack_at_descriptor_path_read_only(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text()
        self.assertIn(
            "${RETRO_REWIND_INSTALL_ROOT:-/srv/emulator/retro-rewind}:/config/retro-rewind:ro",
            compose,
        )
        self.assertIn(
            "RETRO_REWIND_DESCRIPTOR: /config/retro-rewind/launch/RetroRewind.json",
            compose,
        )

    def test_compose_keeps_mii_wrapper_outermost(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text()
        self.assertIn("DOLPHIN_BIN: /opt/romm/bin/dolphin-mii-wrapper.sh", compose)
        self.assertIn(
            "DOLPHIN_REAL_BIN: /opt/romm/bin/dolphin-retro-rewind-wrapper.py",
            compose,
        )
        self.assertIn("DOLPHIN_FINAL_BIN: /usr/local/bin/dolphin-emu", compose)


if __name__ == "__main__":
    unittest.main()
