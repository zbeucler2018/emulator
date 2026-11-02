#!/usr/bin/env python3
"""Minimal RomM legacy-broker adapter for LinuxServer's Steam container.

The adapter intentionally owns no stream implementation.  LinuxServer Steam's
Selkies service remains the browser endpoint; this process only validates a
RomM-owned AppID descriptor and asks the already-running Steam client to launch
it.  The API is private to the Compose network and every mutating request is
authenticated with RomM's existing broker secret.
"""

from __future__ import annotations

import argparse
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urlparse


MAX_BODY_BYTES = 64 * 1024
MAX_DESCRIPTOR_BYTES = 64 * 1024
LAUNCH_GRACE_SECONDS = 120.0


class BrokerError(RuntimeError):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


class SteamBroker:
    def __init__(
        self,
        *,
        secret: str,
        catalog_root: Path,
        steam_bin: str = "/usr/bin/steam",
        state_path: Path = Path("/config/.cache/romm-steam-broker/session.json"),
    ) -> None:
        if not secret:
            raise ValueError("STEAM_BROKER_SECRET is required")
        self.secret = secret
        self.catalog_root = catalog_root.resolve()
        self.steam_bin = steam_bin
        self.state_path = state_path
        self._lock = threading.Lock()
        self._session: dict[str, Any] | None = self._read_state()
        # The state file survives a broker/container restart. Reconcile it
        # against Steam's per-game process before accepting new work.
        self._reconcile_session()

    def authorized(self, presented: str | None) -> bool:
        return bool(presented) and hmac.compare_digest(self.secret, presented or "")

    def _read_state(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _write_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        if self._session is None:
            self.state_path.unlink(missing_ok=True)
            return
        temporary = self.state_path.with_name(f".{self.state_path.name}.{os.getpid()}")
        temporary.write_text(json.dumps(self._session, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.state_path)

    def descriptor(self, raw_path: str) -> dict[str, Any]:
        try:
            path = Path(raw_path).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise BrokerError(HTTPStatus.NOT_FOUND, f"Steam descriptor is unavailable: {raw_path}") from exc
        if not path.is_relative_to(self.catalog_root):
            raise BrokerError(HTTPStatus.BAD_REQUEST, "Steam descriptor is outside the catalog root")
        if path.suffix != ".steam" or not path.is_file():
            raise BrokerError(HTTPStatus.UNPROCESSABLE_ENTITY, "Steam launch target must be a .steam descriptor")
        if path.stat().st_size > MAX_DESCRIPTOR_BYTES:
            raise BrokerError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Steam descriptor is too large")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrokerError(HTTPStatus.UNPROCESSABLE_ENTITY, "Steam descriptor is invalid JSON") from exc
        appid = value.get("appid") if isinstance(value, dict) else None
        if (
            value.get("type") != "romm-steam-app"
            or value.get("version") != 1
            or not isinstance(appid, int)
            or isinstance(appid, bool)
            or appid <= 0
        ):
            raise BrokerError(HTTPStatus.UNPROCESSABLE_ENTITY, "Steam descriptor identity is invalid")
        return value

    @staticmethod
    def _steam_user_id(proc_root: Path = Path("/proc")) -> int | None:
        """Return the active Steam account ID advertised by steamwebhelper.

        Steam starts its login UI with ``--steamid=0`` and starts authenticated
        helpers with the account's non-zero Steam ID.  This is a live-session
        check, unlike loginusers.vdf, which can remain after a user signs out.
        """
        for entry in proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                arguments = [
                    os.fsdecode(argument)
                    for argument in (entry / "cmdline").read_bytes().split(b"\0")
                    if argument
                ]
            except (OSError, PermissionError):
                continue
            if not arguments or "steamwebhelper" not in Path(arguments[0]).name:
                continue
            for argument in arguments[1:]:
                if not argument.startswith("--steamid="):
                    continue
                try:
                    steam_id = int(argument.partition("=")[2])
                except ValueError:
                    continue
                if steam_id > 0:
                    return steam_id
        return None

    @staticmethod
    def _app_processes(appid: int, proc_root: Path = Path("/proc")) -> list[int]:
        """Find only processes belonging to one Steam AppID.

        Steam's per-game reaper is the primary lifecycle signal. Its command
        line contains ``SteamLaunch AppId=<appid>`` from launch until exit for
        native and Proton games. Environment markers remain a fallback for a
        game child, but the shared Steam client is never a stop target.
        """
        found: set[int] = set()
        signature = f"SteamLaunch AppId={appid}"
        for entry in proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                raw_cmdline = (entry / "cmdline").read_bytes()
                arguments = raw_cmdline.rstrip(b"\0").split(b"\0")
                cmdline = (
                    raw_cmdline.replace(b"\0", b" ")
                    .decode("utf-8", "replace")
                    .rstrip()
                )
            except (OSError, PermissionError):
                arguments = []
                cmdline = ""

            index = cmdline.find(signature)
            after = (
                cmdline[index + len(signature) : index + len(signature) + 1]
                if index >= 0
                else ""
            )
            if "reaper" in cmdline and index >= 0 and after in ("", " "):
                found.add(int(entry.name))
                continue

            try:
                fields = (entry / "environ").read_bytes().split(b"\0")
            except (OSError, PermissionError):
                continue
            process_appid = None
            for field in fields:
                if field.startswith((b"SteamAppId=", b"SteamGameId=")):
                    try:
                        process_appid = int(field.split(b"=", 1)[1])
                    except ValueError:
                        pass
                    if process_appid:
                        break
            executable = Path(os.fsdecode(arguments[0])).name if arguments else ""
            if process_appid == appid and executable not in {"steam", "steamwebhelper"}:
                found.add(int(entry.name))
        return sorted(found)

    def _clear_session(self) -> None:
        self._session = None
        self._write_state()

    def _reconcile_session(self, *, now: float | None = None) -> tuple[str, list[int]]:
        """Refresh persisted state without a poller or background daemon."""
        if self._session is None:
            return "idle", []
        try:
            appid = int(self._session["appid"])
            accepted_at = float(self._session["accepted_at"])
        except (KeyError, TypeError, ValueError):
            self._clear_session()
            return "idle", []

        pids = self._app_processes(appid)
        if pids:
            if not self._session.get("seen_running"):
                self._session["seen_running"] = True
                self._write_state()
            return "running", pids

        current_time = time.time() if now is None else now
        if self._session.get("seen_running") or current_time - accepted_at >= LAUNCH_GRACE_SECONDS:
            self._clear_session()
            return "idle", []
        return "launching", []

    def launch(self, raw_path: str, rom_name: str | None = None) -> dict[str, Any]:
        value = self.descriptor(raw_path)
        with self._lock:
            self._reconcile_session()
            if self._session is not None:
                raise BrokerError(HTTPStatus.CONFLICT, "a Steam session is already active")
            if self._steam_user_id() is None:
                raise BrokerError(
                    HTTPStatus.PRECONDITION_FAILED,
                    "Steam is not signed in; open /steam/ and sign in before launching a game",
                )
            appid = value["appid"]
            try:
                completed = subprocess.run(
                    [self.steam_bin, "-applaunch", str(appid)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=8,
                    check=False,
                    start_new_session=True,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise BrokerError(HTTPStatus.BAD_GATEWAY, f"could not invoke Steam: {exc}") from exc
            # The Steam CLI normally hands the request to the running client and
            # exits 0.  A login screen may still be required; this response only
            # means Steam accepted the AppID, never that gameplay was observed.
            if completed.returncode != 0:
                detail = (completed.stderr or "Steam rejected the launch request").strip()
                raise BrokerError(HTTPStatus.BAD_GATEWAY, detail[:2048])
            self._session = {
                "appid": appid,
                "name": value.get("name") or rom_name,
                "descriptor": raw_path,
                "accepted_at": time.time(),
                "seen_running": False,
            }
            self._write_state()
            return {"status": "launching", "appid": appid}

    def status(self) -> dict[str, Any]:
        with self._lock:
            state, pids = self._reconcile_session()
            if self._session is None:
                return {"status": "idle"}
            appid = int(self._session["appid"])
            return {
                "status": state,
                "appid": appid,
                "pids": pids,
                "accepted_at": self._session.get("accepted_at"),
            }

    def stop(self, *, timeout: float = 30.0) -> dict[str, Any]:
        with self._lock:
            _, pids = self._reconcile_session()
            if self._session is None:
                return {"status": "idle", "stopped": 0}
            appid = int(self._session["appid"])
            # SIGTERM gives the per-game Steam reaper and game children a
            # chance to unwind while leaving the shared Steam client alive.
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + timeout
            remaining = pids
            while remaining and time.monotonic() < deadline:
                time.sleep(0.2)
                live = self._app_processes(appid)
                remaining = [pid for pid in remaining if pid in live]
            # A hung game gets one last-resort force stop. Re-scan before each
            # signal so a recycled PID can never terminate an unrelated task.
            live = set(self._app_processes(appid)) if remaining else set()
            remaining = [pid for pid in remaining if pid in live]
            for pid in remaining:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self._clear_session()
            return {
                "status": "stopped",
                "stopped": len(pids),
                "graceful": len(pids) - len(remaining),
                "forced": len(remaining),
            }


class BrokerHandler(BaseHTTPRequestHandler):
    server: "BrokerServer"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"steam-broker: {self.address_string()} {fmt % args}", flush=True)

    def _json(self, status: int, value: object) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _require_secret(self) -> None:
        if not self.server.broker.authorized(self.headers.get("X-Broker-Secret")):
            raise BrokerError(HTTPStatus.FORBIDDEN, "invalid broker secret")

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise BrokerError(HTTPStatus.BAD_REQUEST, "invalid content length") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise BrokerError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request is too large")
        try:
            value = json.loads(self.rfile.read(length) if length else b"{}")
        except json.JSONDecodeError as exc:
            raise BrokerError(HTTPStatus.BAD_REQUEST, "request is invalid JSON") from exc
        if not isinstance(value, dict):
            raise BrokerError(HTTPStatus.BAD_REQUEST, "request body must be an object")
        return value

    def _dispatch(self, method: str) -> None:
        try:
            path = urlparse(self.path).path
            if method == "GET" and path == "/health":
                self._json(HTTPStatus.OK, {"status": "ok"})
                return
            self._require_secret()
            if method == "GET" and path == "/status":
                self._json(HTTPStatus.OK, self.server.broker.status())
            elif method == "POST" and path == "/launch":
                body = self._body()
                rom_path = body.get("rom_path")
                if not isinstance(rom_path, str):
                    raise BrokerError(HTTPStatus.UNPROCESSABLE_ENTITY, "rom_path is required")
                self._json(
                    HTTPStatus.OK,
                    self.server.broker.launch(rom_path, body.get("rom_name")),
                )
            elif method == "DELETE" and path == "/launch":
                self._json(HTTPStatus.OK, self.server.broker.stop())
            elif method == "POST" and path == "/save-and-exit":
                stopped = self.server.broker.stop()
                self._json(HTTPStatus.OK, {**stopped, "saved": False, "slot": 0})
            elif path in ("/save-file", "/state-file"):
                raise BrokerError(HTTPStatus.NOT_FOUND, "Steam persistence is managed by /config and Steam Cloud")
            elif method == "POST" and path == "/volume":
                self._json(HTTPStatus.OK, {"status": "ok"})
            elif method == "POST" and path == "/mute":
                self._json(HTTPStatus.OK, {"mute": False})
            else:
                raise BrokerError(HTTPStatus.NOT_FOUND, "route not found")
        except BrokerError as exc:
            self._json(exc.status, {"detail": exc.detail})
        except Exception as exc:  # pragma: no cover - defensive server boundary
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"detail": f"internal broker error: {exc}"})

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")


class BrokerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], broker: SteamBroker):
        self.broker = broker
        super().__init__(address, BrokerHandler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default=os.environ.get("STEAM_BROKER_BIND", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("STEAM_BROKER_PORT", "8000")))
    args = parser.parse_args()
    broker = SteamBroker(
        secret=os.environ.get("STEAM_BROKER_SECRET", ""),
        catalog_root=Path(os.environ.get("STEAM_CATALOG_ROOT", "/romm/library/roms/Steam")),
        steam_bin=os.environ.get("STEAM_BIN", "/usr/bin/steam"),
    )
    server = BrokerServer((args.bind, args.port), broker)
    print(f"steam-broker: listening on {args.bind}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
