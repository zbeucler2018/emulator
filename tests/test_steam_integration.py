#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


library = load_module("steam_library", ROOT / "scripts" / "steam-library.py")
broker = load_module("steam_broker", ROOT / "scripts" / "steam-broker.py")


def manifest(root: Path, appid: int, name: str, installdir: str, size: int = 123) -> Path:
    steamapps = root / "steamapps"
    (steamapps / "common" / installdir).mkdir(parents=True, exist_ok=True)
    path = steamapps / f"appmanifest_{appid}.acf"
    path.write_text(
        f'''"AppState"
{{
    "appid"        "{appid}"
    "name"         "{name}"
    "installdir"   "{installdir}"
    "SizeOnDisk"   "{size}"
    "UserConfig"
    {{
        "language" "english"
    }}
}}
''',
        encoding="utf-8",
    )
    return path


class LibraryDiscoveryTests(unittest.TestCase):
    def test_discovers_games_and_excludes_tools_from_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "host"
            manifest(root, 892970, "Valheim", "Valheim")
            manifest(root, 1493710, "Proton Experimental", "Proton - Experimental")
            apps = library.discover(root)
            self.assertEqual([app.appid for app in apps], [1493710, 892970])
            destination = Path(temporary) / "catalog"
            written = library.write_catalog(apps, destination, prune=False)
            self.assertEqual(len(written), 1)
            value = json.loads(written[0].read_text())
            self.assertEqual(value["appid"], 892970)
            self.assertEqual(written[0].name, "Valheim (steam-892970).steam")

    def test_stage_copies_manifest_and_links_read_only_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "host"
            app_manifest = manifest(root, 892970, "Valheim", "Valheim")
            target = Path(temporary) / "isolated"
            [staged] = library.stage_library(library.discover(root), target)
            self.assertEqual(staged.read_bytes(), app_manifest.read_bytes())
            link = target / "steamapps" / "common" / "Valheim"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), (root / "steamapps" / "common" / "Valheim").resolve())

    def test_stage_refuses_to_replace_real_container_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "host"
            manifest(root, 892970, "Valheim", "Valheim")
            target = Path(temporary) / "isolated"
            (target / "steamapps" / "common" / "Valheim").mkdir(parents=True)
            with self.assertRaisesRegex(library.SteamLibraryError, "non-symlink"):
                library.stage_library(library.discover(root), target)

    def test_stage_gives_proton_a_writable_shim_without_copying_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "host"
            manifest(root, 1493710, "Proton Experimental", "Proton - Experimental")
            payload = root / "steamapps" / "common" / "Proton - Experimental" / "proton"
            payload.write_text("large payload")
            target = Path(temporary) / "isolated"
            library.stage_library(library.discover(root), target)
            view = target / "steamapps" / "common" / "Proton - Experimental"
            self.assertTrue(view.is_dir())
            self.assertFalse(view.is_symlink())
            self.assertTrue((view / "proton").is_symlink())
            (view / "user_settings.py").write_text("container setting")
            self.assertFalse((root / "steamapps" / "common" / "Proton - Experimental" / "user_settings.py").exists())

    def test_prune_only_removes_owned_descriptors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "host"
            manifest(root, 892970, "Valheim", "Valheim")
            destination = Path(temporary) / "catalog"
            destination.mkdir()
            managed = destination / "old.steam"
            managed.write_text(json.dumps({"managed_by": library.MANAGED_BY}))
            unmanaged = destination / "manual.steam"
            unmanaged.write_text(json.dumps({"managed_by": "user"}))
            library.write_catalog(library.discover(root), destination, prune=True)
            self.assertFalse(managed.exists())
            self.assertTrue(unmanaged.exists())


class BrokerTests(unittest.TestCase):
    def _tree(self, root: Path) -> tuple[Path, Path]:
        catalog = root / "catalog"
        catalog.mkdir()
        descriptor = catalog / "Valheim (steam-892970).steam"
        descriptor.write_text(
            json.dumps(
                {
                    "type": "romm-steam-app",
                    "version": 1,
                    "appid": 892970,
                    "name": "Valheim",
                }
            )
        )
        return catalog, descriptor

    def test_descriptor_validation_confines_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, descriptor = self._tree(root)
            instance = broker.SteamBroker(
                secret="secret", catalog_root=catalog, state_path=root / "state.json"
            )
            self.assertEqual(instance.descriptor(str(descriptor))["appid"], 892970)
            outside = root / "outside.steam"
            outside.write_text(descriptor.read_text())
            with self.assertRaisesRegex(broker.BrokerError, "outside"):
                instance.descriptor(str(outside))

    def test_launch_constructs_direct_appid_command_and_tracks_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, descriptor = self._tree(root)
            instance = broker.SteamBroker(
                secret="secret",
                catalog_root=catalog,
                steam_bin="/usr/bin/steam",
                state_path=root / "state.json",
            )
            completed = mock.Mock(returncode=0, stderr="")
            with mock.patch.object(broker.subprocess, "run", return_value=completed) as run:
                result = instance.launch(str(descriptor))
            self.assertEqual(result, {"status": "launching", "appid": 892970})
            self.assertEqual(run.call_args.args[0], ["/usr/bin/steam", "-applaunch", "892970"])
            with self.assertRaisesRegex(broker.BrokerError, "already active"):
                instance.launch(str(descriptor))

    def test_stop_terminates_only_the_active_appid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, descriptor = self._tree(root)
            instance = broker.SteamBroker(
                secret="secret", catalog_root=catalog, state_path=root / "state.json"
            )
            with mock.patch.object(broker.subprocess, "run", return_value=mock.Mock(returncode=0, stderr="")):
                instance.launch(str(descriptor))
            with (
                mock.patch.object(instance, "_process_appids", side_effect=[{892970: [111]}, {}]),
                mock.patch.object(broker.os, "kill") as kill,
            ):
                result = instance.stop(timeout=0.1)
            kill.assert_called_once_with(111, broker.signal.SIGTERM)
            self.assertEqual(result["forced"], 0)
            self.assertEqual(instance.status()["status"], "idle")

    def test_broker_secret_is_constant_time_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, _ = self._tree(root)
            instance = broker.SteamBroker(
                secret="secret", catalog_root=catalog, state_path=root / "state.json"
            )
            self.assertTrue(instance.authorized("secret"))
            self.assertFalse(instance.authorized("wrong"))
            self.assertFalse(instance.authorized(None))

    def test_restart_discards_a_stale_persisted_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, _ = self._tree(root)
            state = root / "state.json"
            state.write_text(json.dumps({"appid": 892970, "accepted_at": 1}))
            with mock.patch.object(broker.SteamBroker, "_process_appids", return_value={}):
                instance = broker.SteamBroker(
                    secret="secret", catalog_root=catalog, state_path=state
                )
            self.assertEqual(instance.status(), {"status": "idle"})
            self.assertFalse(state.exists())


class DeploymentWiringTests(unittest.TestCase):
    def test_compose_is_optional_pinned_and_read_only(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text()
        self.assertIn('profiles: ["steam"]', compose)
        self.assertIn("lscr.io/linuxserver/steam@sha256:", compose)
        self.assertIn("STEAM_HOST_LIBRARY_PATH", compose)
        self.assertIn("/mnt/host-steam:ro", compose)
        self.assertIn("STEAM_API_ENABLED: ${STEAM_API_ENABLED:-true}", compose)
        self.assertNotIn("/var/run/docker.sock", compose)

    def test_romm_routes_linux_to_the_private_broker(self) -> None:
        config = (ROOT / "config" / "config.yml").read_text()
        self.assertIn("Steam: linux", config)
        self.assertIn("broker_host: http://steam:8000", config)
        self.assertIn("emulator: steam", config)


if __name__ == "__main__":
    unittest.main()
