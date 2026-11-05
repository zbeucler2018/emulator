#!/usr/bin/env python3
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
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
steam_user_id = broker.SteamBroker._steam_user_id


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

    def test_stage_copies_only_selected_proton_runtime_to_writable_state(self) -> None:
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
            self.assertFalse((view / "proton").is_symlink())
            self.assertTrue((view / library.WRITABLE_TOOL_MARKER).is_file())
            (view / "user_settings.py").write_text("container setting")
            self.assertFalse((root / "steamapps" / "common" / "Proton - Experimental" / "user_settings.py").exists())

            # A later init preserves Steam's local tool updates.
            (view / "proton").write_text("container update")
            library.stage_library(library.discover(root), target)
            self.assertEqual((view / "proton").read_text(), "container update")

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
    def setUp(self) -> None:
        signed_in = mock.patch.object(
            broker.SteamBroker, "_steam_user_id", return_value=76561198000000000
        )
        signed_in.start()
        self.addCleanup(signed_in.stop)

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

    def test_process_detection_prefers_reaper_and_excludes_shared_steam(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary)

            def process(pid: int, arguments: list[str], environment: list[str]) -> None:
                directory = proc / str(pid)
                directory.mkdir()
                (directory / "cmdline").write_bytes(
                    b"\0".join(arg.encode() for arg in arguments) + b"\0"
                )
                (directory / "environ").write_bytes(
                    b"\0".join(item.encode() for item in environment) + b"\0"
                )

            process(111, ["reaper", "SteamLaunch", "AppId=892970", "--", "game"], [])
            process(222, ["wine64", "game.exe"], ["SteamAppId=892970"])
            process(333, ["reaper", "SteamLaunch", "AppId=8929700", "--"], [])
            process(444, ["/usr/bin/steam"], ["SteamGameId=892970"])

            self.assertEqual(broker.SteamBroker._app_processes(892970, proc), [111, 222])

    def test_live_steam_login_detection_rejects_zero_account(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary)

            def helper(pid: int, steam_id: str) -> None:
                directory = proc / str(pid)
                directory.mkdir()
                (directory / "cmdline").write_bytes(
                    b"/steam/steamwebhelper\0--steamid=" + steam_id.encode() + b"\0"
                )

            helper(111, "0")
            self.assertIsNone(steam_user_id(proc))
            helper(222, "76561198000000000")
            self.assertEqual(steam_user_id(proc), 76561198000000000)

    def test_connection_log_detects_login_and_later_disconnect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc = root / "proc"
            proc.mkdir()
            connection_log = root / "connection_log.txt"
            connection_log.write_text(
                "[time] [Connecting, 0, 0] [U:1:0] starting\n"
                "[time] [Logged On, 4, 107] [U:1:1601339192] complete\n"
            )
            self.assertEqual(steam_user_id(proc, connection_log), 1601339192)
            connection_log.write_text(
                connection_log.read_text()
                + "[time] [Disconnected, 0, 0] [U:1:1601339192] closed\n"
            )
            self.assertIsNone(steam_user_id(proc, connection_log))

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
            with (
                mock.patch.object(broker.subprocess, "run", return_value=completed) as run,
                mock.patch.object(instance, "_start_ubisoft_window_nudge") as nudge,
            ):
                result = instance.launch(str(descriptor))
            self.assertEqual(result, {"status": "launching", "appid": 892970})
            self.assertEqual(run.call_args.args[0], ["/usr/bin/steam", "-applaunch", "892970"])
            nudge.assert_called_once_with()
            with self.assertRaisesRegex(broker.BrokerError, "already active"):
                instance.launch(str(descriptor))

    def test_ubisoft_window_nudge_resizes_and_remaps_exact_window(self) -> None:
        found = mock.Mock(stdout="123\n")
        geometry = mock.Mock(stdout="WIDTH=714\nHEIGHT=454\n")
        display = mock.Mock(stdout="1920 1080\n")
        completed = mock.Mock(stdout="")
        with mock.patch.object(
            broker.subprocess,
            "run",
            side_effect=[
                found,
                geometry,
                display,
                completed,
                completed,
                completed,
                completed,
                completed,
            ],
        ) as run:
            broker.SteamBroker._nudge_ubisoft_window(
                timeout=1,
                initial_settle=0,
                resize_settle=0,
                remap_settle=0,
                focus_guard=0,
            )

        self.assertEqual(
            run.call_args_list[0].args[0],
            [
                "/usr/bin/xdotool",
                "search",
                "--onlyvisible",
                "--name",
                "^Ubisoft Connect$",
            ],
        )
        self.assertEqual(
            run.call_args_list[2].args[0],
            ["/usr/bin/xdotool", "getdisplaygeometry"],
        )
        self.assertEqual(
            run.call_args_list[3].args[0],
            ["/usr/bin/xdotool", "windowsize", "123", "714", "454"],
        )
        self.assertEqual(
            run.call_args_list[4].args[0],
            ["/usr/bin/xdotool", "windowsize", "123", "716", "456"],
        )
        self.assertEqual(
            run.call_args_list[5].args[0],
            ["/usr/bin/xdotool", "windowunmap", "123"],
        )
        self.assertEqual(
            run.call_args_list[6].args[0],
            ["/usr/bin/xdotool", "windowmap", "--sync", "123"],
        )
        self.assertEqual(
            run.call_args_list[7].args[0],
            ["/usr/bin/xdotool", "windowfocus", "--sync", "123"],
        )

    def test_ubisoft_window_nudge_pulses_down_at_display_bounds(self) -> None:
        found = mock.Mock(stdout="123\n")
        geometry = mock.Mock(stdout="WIDTH=1920\nHEIGHT=1080\n")
        display = mock.Mock(stdout="1920 1080\n")
        completed = mock.Mock(stdout="")
        with mock.patch.object(
            broker.subprocess,
            "run",
            side_effect=[
                found,
                geometry,
                display,
                completed,
                completed,
                completed,
                completed,
                completed,
            ],
        ) as run:
            broker.SteamBroker._nudge_ubisoft_window(
                timeout=1,
                initial_settle=0,
                resize_settle=0,
                remap_settle=0,
                focus_guard=0,
            )

        self.assertEqual(
            run.call_args_list[3].args[0],
            ["/usr/bin/xdotool", "windowsize", "123", "1918", "1078"],
        )
        self.assertEqual(
            run.call_args_list[4].args[0],
            ["/usr/bin/xdotool", "windowsize", "123", "1920", "1080"],
        )

    def test_ubisoft_window_nudge_retries_during_display_reconfiguration(self) -> None:
        found = mock.Mock(stdout="123\n")
        geometry = mock.Mock(stdout="WIDTH=1918\nHEIGHT=1078\n")
        display = mock.Mock(stdout="1920 1080\n")
        completed = mock.Mock(stdout="")
        with (
            mock.patch.object(
                broker.subprocess,
                "run",
                side_effect=[
                    broker.subprocess.TimeoutExpired("xdotool", 2),
                    found,
                    geometry,
                    display,
                    completed,
                    completed,
                    completed,
                    completed,
                    completed,
                ],
            ) as run,
            mock.patch.object(broker.time, "sleep"),
        ):
            broker.SteamBroker._nudge_ubisoft_window(
                timeout=1,
                initial_settle=0,
                resize_settle=0,
                remap_settle=0,
                focus_guard=0,
            )

        self.assertEqual(run.call_count, 9)

    def test_ubisoft_focus_guard_repairs_active_window_focus(self) -> None:
        active = mock.Mock(stdout="100\n")
        title = mock.Mock(stdout="Ubisoft Connect\n")
        focused = mock.Mock(stdout="200\n")
        completed = mock.Mock(stdout="")
        with (
            mock.patch.object(
                broker.subprocess,
                "run",
                side_effect=[active, title, focused, completed],
            ) as run,
            mock.patch.object(broker.time, "monotonic", side_effect=[0, 0, 2]),
            mock.patch.object(broker.time, "sleep"),
        ):
            broker.SteamBroker._guard_ubisoft_keyboard_focus(timeout=1, poll=0)

        self.assertEqual(
            run.call_args_list[-1].args[0],
            ["/usr/bin/xdotool", "windowfocus", "--sync", "100"],
        )

    def test_rejected_launch_does_not_create_a_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, descriptor = self._tree(root)
            instance = broker.SteamBroker(
                secret="secret", catalog_root=catalog, state_path=root / "state.json"
            )
            completed = mock.Mock(returncode=1, stderr="not signed in")
            with (
                mock.patch.object(broker.subprocess, "run", return_value=completed),
                self.assertRaisesRegex(broker.BrokerError, "not signed in"),
            ):
                instance.launch(str(descriptor))
            self.assertEqual(instance.status(), {"status": "idle"})
            self.assertFalse((root / "state.json").exists())

    def test_unsigned_in_launch_is_rejected_without_reserving_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, descriptor = self._tree(root)
            instance = broker.SteamBroker(
                secret="secret", catalog_root=catalog, state_path=root / "state.json"
            )
            with (
                mock.patch.object(instance, "_steam_user_id", return_value=None),
                mock.patch.object(broker.subprocess, "run") as run,
                self.assertRaisesRegex(broker.BrokerError, "not signed in") as raised,
            ):
                instance.launch(str(descriptor))
            self.assertEqual(raised.exception.status, 412)
            run.assert_not_called()
            self.assertEqual(instance.status(), {"status": "idle"})
            self.assertFalse((root / "state.json").exists())

    def test_session_clears_after_observed_game_exits_and_allows_relaunch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, descriptor = self._tree(root)
            instance = broker.SteamBroker(
                secret="secret", catalog_root=catalog, state_path=root / "state.json"
            )
            completed = mock.Mock(returncode=0, stderr="")
            with mock.patch.object(broker.subprocess, "run", return_value=completed):
                instance.launch(str(descriptor))
                with mock.patch.object(instance, "_app_processes", side_effect=[[111], []]):
                    self.assertEqual(instance.status()["status"], "running")
                    self.assertEqual(instance.status(), {"status": "idle"})
                self.assertEqual(instance.launch(str(descriptor))["status"], "launching")

    def test_session_clears_when_accepted_game_never_starts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, descriptor = self._tree(root)
            instance = broker.SteamBroker(
                secret="secret", catalog_root=catalog, state_path=root / "state.json"
            )
            completed = mock.Mock(returncode=0, stderr="")
            with (
                mock.patch.object(broker.subprocess, "run", return_value=completed),
                mock.patch.object(broker.time, "time", return_value=100.0),
            ):
                instance.launch(str(descriptor))
            with (
                mock.patch.object(instance, "_app_processes", return_value=[]),
                mock.patch.object(broker.time, "time", return_value=221.0),
            ):
                self.assertEqual(instance.status(), {"status": "idle"})
            self.assertFalse((root / "state.json").exists())

    def test_concurrent_launches_create_only_one_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, descriptor = self._tree(root)
            instance = broker.SteamBroker(
                secret="secret", catalog_root=catalog, state_path=root / "state.json"
            )
            gate = threading.Barrier(3)

            def launch() -> str:
                gate.wait()
                try:
                    return instance.launch(str(descriptor))["status"]
                except broker.BrokerError as exc:
                    return f"error:{exc.status}"

            completed = mock.Mock(returncode=0, stderr="")
            with mock.patch.object(broker.subprocess, "run", return_value=completed):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(launch) for _ in range(2)]
                    gate.wait()
                    results = sorted(future.result() for future in futures)
            self.assertEqual(results, ["error:409", "launching"])
            self.assertEqual(completed.returncode, 0)

    def test_stop_terminates_only_the_active_appid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, descriptor = self._tree(root)
            instance = broker.SteamBroker(
                secret="secret", catalog_root=catalog, state_path=root / "state.json"
            )
            with mock.patch.object(
                broker.subprocess,
                "run",
                return_value=mock.Mock(returncode=0, stderr=""),
            ):
                instance.launch(str(descriptor))
            with (
                mock.patch.object(instance, "_app_processes", side_effect=[[111], []]),
                mock.patch.object(broker.os, "kill") as kill,
            ):
                result = instance.stop(timeout=0.1)
            kill.assert_called_once_with(111, broker.signal.SIGTERM)
            self.assertEqual(result["forced"], 0)
            self.assertEqual(result["graceful"], 1)
            self.assertEqual(instance.status()["status"], "idle")

    def test_cancel_before_game_appears_clears_session_without_signals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, descriptor = self._tree(root)
            instance = broker.SteamBroker(
                secret="secret", catalog_root=catalog, state_path=root / "state.json"
            )
            with mock.patch.object(broker.subprocess, "run", return_value=mock.Mock(returncode=0, stderr="")):
                instance.launch(str(descriptor))
            with (
                mock.patch.object(instance, "_app_processes", return_value=[]),
                mock.patch.object(broker.os, "kill") as kill,
            ):
                result = instance.stop()
            kill.assert_not_called()
            self.assertEqual(
                result,
                {"status": "stopped", "stopped": 0, "graceful": 0, "forced": 0},
            )
            self.assertFalse((root / "state.json").exists())

    def test_stop_uses_sigkill_only_for_the_still_matching_app_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, descriptor = self._tree(root)
            instance = broker.SteamBroker(
                secret="secret", catalog_root=catalog, state_path=root / "state.json"
            )
            with mock.patch.object(
                broker.subprocess,
                "run",
                return_value=mock.Mock(returncode=0, stderr=""),
            ):
                instance.launch(str(descriptor))
            with (
                mock.patch.object(instance, "_app_processes", side_effect=[[111, 222], [222]]),
                mock.patch.object(broker.os, "kill") as kill,
            ):
                result = instance.stop(timeout=0)
            self.assertEqual(
                kill.call_args_list,
                [
                    mock.call(111, broker.signal.SIGTERM),
                    mock.call(222, broker.signal.SIGTERM),
                    mock.call(222, broker.signal.SIGKILL),
                ],
            )
            self.assertEqual(result["graceful"], 1)
            self.assertEqual(result["forced"], 1)

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
            with mock.patch.object(broker.SteamBroker, "_app_processes", return_value=[]):
                instance = broker.SteamBroker(
                    secret="secret", catalog_root=catalog, state_path=state
                )
            self.assertEqual(instance.status(), {"status": "idle"})
            self.assertFalse(state.exists())

    def test_restart_preserves_a_still_running_game_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, _ = self._tree(root)
            state = root / "state.json"
            state.write_text(json.dumps({"appid": 892970, "accepted_at": 1}))
            with mock.patch.object(
                broker.SteamBroker, "_app_processes", return_value=[111]
            ):
                instance = broker.SteamBroker(
                    secret="secret", catalog_root=catalog, state_path=state
                )
                status = instance.status()
            self.assertEqual(status["status"], "running")
            self.assertEqual(status["pids"], [111])
            self.assertTrue(json.loads(state.read_text())["seen_running"])


class DeploymentWiringTests(unittest.TestCase):
    def test_compose_exposes_matching_32_bit_nvidia_vulkan_driver(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text()
        for library in (
            "libGLX_nvidia.so.580.178.04",
            "libnvidia-glcore.so.580.178.04",
            "libnvidia-tls.so.580.178.04",
            "libnvidia-glsi.so.580.178.04",
            "libnvidia-gpucomp.so.580.178.04",
            "libnvidia-glvkspirv.so.580.178.04",
        ):
            path = f"/usr/lib/i386-linux-gnu/{library}"
            self.assertIn(f"- {path}:{path}:ro", compose)
        self.assertIn(
            "/usr/lib/i386-linux-gnu/libGLX_nvidia.so.580.178.04:"
            "/usr/lib/i386-linux-gnu/libGLX_nvidia.so.0:ro",
            compose,
        )

    def test_compose_is_optional_pinned_and_library_is_writable(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text()
        self.assertIn('profiles: ["steam"]', compose)
        self.assertIn(
            "image: lscr.io/linuxserver/steam@sha256:f3d8f5e8c80c5ce809c839ada788fd69132b2314fcad2e7804ca725671aa5c65",
            compose,
        )
        self.assertNotIn("STEAM_IMAGE", compose)
        self.assertIn(
            "/home/service/snap/steam/common/.local/share/Steam/steamapps:/mnt/host-steam/steamapps:rw",
            compose,
        )
        self.assertIn('"127.0.0.1:3020:3000"', compose)
        self.assertIn('- "44"', compose)
        self.assertIn('- "992"', compose)
        self.assertIn('"c 10:223 rwm"', compose)
        self.assertIn('"c 13:* rwm"', compose)
        self.assertNotIn('"c 13:85 rwm"', compose)
        self.assertNotIn('"c 13:1 rwm"', compose)
        self.assertNotIn("/dev/uinput:/dev/uinput", compose)
        self.assertIn('SELKIES_UINPUT_GAMEPAD: "true"', compose)
        self.assertNotIn("privileged: true", compose)
        self.assertIn('STEAM_API_ENABLED: "true"', compose)
        self.assertNotIn("STEAM_API_ENABLED=", (ROOT / ".env.example").read_text())
        self.assertNotIn("/var/run/docker.sock", compose)

    def test_romm_routes_linux_to_the_private_broker(self) -> None:
        config = (ROOT / "config" / "config.yml").read_text()
        self.assertIn("Steam: linux", config)
        self.assertIn("host: /steam/?romm=1", config)
        self.assertIn("broker_host: http://steam:8000", config)
        self.assertIn("emulator: steam", config)

    def test_selkies_has_an_explicit_steam_asset_base(self) -> None:
        init = (
            ROOT
            / "config"
            / "steam"
            / "custom-cont-init.d"
            / "30-selkies-base-path"
        ).read_text()
        self.assertIn('<base href="/steam/">', init)

    def test_steam_starts_in_controller_oriented_big_picture(self) -> None:
        init = (
            ROOT
            / "config"
            / "steam"
            / "custom-cont-init.d"
            / "20-harden-steam-ui"
        ).read_text()
        self.assertIn("/usr/bin/wrapped-steam -gamepadui", init)
        self.assertIn('title="Ubisoft Connect"', init)
        self.assertIn('name="UnSnap"', init)
        self.assertIn('name="ResizeTo" width="1918" height="1078"', init)
        self.assertIn("romm-ubisoft-connect-redraw", init)

    def test_selkies_uinput_node_is_private_to_the_desktop_user(self) -> None:
        init = (
            ROOT
            / "config"
            / "steam"
            / "custom-cont-init.d"
            / "05-uinput-device"
        ).read_text()
        self.assertIn("mknod /dev/uinput c 10 223", init)
        self.assertIn("getent group 995", init)
        self.assertIn('usermod --append --groups "$input_group" abc', init)
        self.assertIn("chown abc:abc /dev/uinput", init)
        self.assertIn("chmod 0600 /dev/uinput", init)
        self.assertIn('[[ -e "/sys/class/input/$node" ]]', init)
        self.assertIn("for index in $(seq 21 28)", init)
        self.assertIn("for index in $(seq 1 8)", init)
        self.assertIn('mknod "$node" c 13 "$((64 + index))"', init)
        self.assertIn('mknod "$node" c 13 "$index"', init)
        self.assertNotIn("/dev/input:/dev/input", init)


if __name__ == "__main__":
    unittest.main()
