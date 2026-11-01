#!/usr/bin/env python3
"""Discover a host Steam library without giving the container write access.

Two deliberately separate operations use the same manifest parser:

``catalog``
    Writes small, owned ``.steam`` descriptors for RomM to index.  The
    descriptor carries only the AppID and installation identity; it is not a
    copy of the game or of Steam account data.

``stage``
    Runs during the Steam container's init.  It copies app manifests into the
    isolated container Steam home and creates read-only symlinks to the host
    installation directories.  Proton prefixes and Steam user data therefore
    stay below the container's persistent ``/config`` volume.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile


DESCRIPTOR_VERSION = 1
DESCRIPTOR_SUFFIX = ".steam"
MANAGED_BY = "emulator/scripts/steam-library.py"
MANIFEST_RE = re.compile(r'^\s*"(?P<key>[^"]+)"\s+"(?P<value>[^"]*)"\s*$')
SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9 ._()'&+!,\-]+")
TOOL_PREFIXES = (
    "proton ",
    "steam linux runtime",
    "steamworks common redistributables",
)


class SteamLibraryError(RuntimeError):
    """A safe, user-facing discovery or staging failure."""


@dataclass(frozen=True)
class SteamApp:
    appid: int
    name: str
    installdir: str
    manifest: Path
    install_path: Path
    size_on_disk: int

    @property
    def is_tool(self) -> bool:
        folded = self.name.casefold()
        return folded.startswith(TOOL_PREFIXES)


def _top_level_fields(path: Path) -> dict[str, str]:
    """Read scalar AppState fields without treating nested VDF values as new apps."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise SteamLibraryError(f"could not read Steam manifest {path}: {exc}") from exc

    fields: dict[str, str] = {}
    depth = 0
    for line in lines:
        stripped = line.strip()
        if stripped == "{":
            depth += 1
            continue
        if stripped == "}":
            depth = max(0, depth - 1)
            continue
        if depth != 1:
            continue
        match = MANIFEST_RE.match(line)
        if match:
            fields[match.group("key").casefold()] = match.group("value")
    return fields


def read_manifest(path: Path, library_root: Path) -> SteamApp:
    fields = _top_level_fields(path)
    try:
        appid = int(fields["appid"])
        size = int(fields.get("sizeondisk", "0"))
    except (KeyError, ValueError) as exc:
        raise SteamLibraryError(f"manifest has no valid AppID/size: {path}") from exc
    name = fields.get("name", "").strip()
    installdir = fields.get("installdir", "").strip()
    if appid <= 0 or not name or not installdir:
        raise SteamLibraryError(f"manifest has invalid identity fields: {path}")
    if Path(installdir).name != installdir or installdir in (".", ".."):
        raise SteamLibraryError(f"manifest has unsafe installdir {installdir!r}: {path}")
    return SteamApp(
        appid=appid,
        name=name,
        installdir=installdir,
        manifest=path,
        install_path=library_root / "steamapps" / "common" / installdir,
        size_on_disk=size,
    )


def discover(library_root: Path) -> list[SteamApp]:
    steamapps = library_root / "steamapps"
    if not steamapps.is_dir():
        raise SteamLibraryError(f"Steam library has no steamapps directory: {steamapps}")
    apps: list[SteamApp] = []
    seen: set[int] = set()
    for manifest in sorted(steamapps.glob("appmanifest_*.acf")):
        app = read_manifest(manifest, library_root)
        if app.appid in seen:
            raise SteamLibraryError(f"duplicate Steam AppID {app.appid} in {steamapps}")
        seen.add(app.appid)
        if not app.install_path.is_dir():
            # A partially downloaded or removed app is not launchable and must
            # not appear as installed merely because its manifest remains.
            continue
        apps.append(app)
    return apps


def _safe_filename(name: str, appid: int) -> str:
    cleaned = SAFE_COMPONENT_RE.sub(" ", name).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = f"Steam {appid}"
    return f"{cleaned} (steam-{appid}){DESCRIPTOR_SUFFIX}"


def descriptor(app: SteamApp) -> dict[str, object]:
    return {
        "type": "romm-steam-app",
        "version": DESCRIPTOR_VERSION,
        "appid": app.appid,
        "name": app.name,
        "installdir": app.installdir,
        "size_on_disk": app.size_on_disk,
        "managed_by": MANAGED_BY,
    }


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def write_catalog(apps: list[SteamApp], destination: Path, *, prune: bool) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    expected: set[Path] = set()
    for app in apps:
        if app.is_tool:
            continue
        target = destination / _safe_filename(app.name, app.appid)
        _write_json_atomic(target, descriptor(app))
        written.append(target)
        expected.add(target.resolve())

    if prune:
        for candidate in destination.glob(f"*{DESCRIPTOR_SUFFIX}"):
            try:
                value = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if value.get("managed_by") != MANAGED_BY:
                continue
            if candidate.resolve() not in expected:
                candidate.unlink()
    return written


def _replace_symlink(link: Path, target: Path) -> None:
    if link.is_symlink():
        if link.resolve() == target.resolve():
            return
        link.unlink()
    elif link.exists():
        raise SteamLibraryError(
            f"refusing to replace non-symlink in isolated Steam library: {link}"
        )
    link.symlink_to(target, target_is_directory=True)


def _stage_proton_view(destination: Path, source: Path) -> None:
    """Expose Proton read-only while leaving its generated settings file writable.

    LinuxServer's Steam wrapper places ``user_settings.py`` at the top of each
    Proton install.  A direct read-only symlink makes its one-second monitor
    retry forever.  This shallow view keeps every large payload entry linked
    to the host and leaves only the view directory itself writable.
    """
    marker = destination / ".romm-readonly-proton-view"
    if destination.is_symlink():
        destination.unlink()
    elif destination.exists() and not marker.is_file():
        raise SteamLibraryError(
            f"refusing to replace non-managed Proton directory: {destination}"
        )
    destination.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"source={source}\n", encoding="utf-8")
    for source_entry in source.iterdir():
        if source_entry.name == "user_settings.py":
            continue
        target = destination / source_entry.name
        if target.is_symlink() and target.resolve() == source_entry.resolve():
            continue
        if target.exists() or target.is_symlink():
            raise SteamLibraryError(
                f"refusing to replace non-managed Proton entry: {target}"
            )
        target.symlink_to(source_entry, target_is_directory=source_entry.is_dir())


def stage_library(apps: list[SteamApp], target_root: Path) -> list[Path]:
    """Stage manifests and links, never writing through to the source library."""
    steamapps = target_root / "steamapps"
    common = steamapps / "common"
    common.mkdir(parents=True, exist_ok=True)
    staged: list[Path] = []
    for app in apps:
        manifest_target = steamapps / f"appmanifest_{app.appid}.acf"
        shutil.copyfile(app.manifest, manifest_target)
        install_target = common / app.installdir
        if app.name.casefold().startswith("proton "):
            _stage_proton_view(install_target, app.install_path)
        else:
            _replace_symlink(install_target, app.install_path)
        staged.append(manifest_target)
    return staged


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(os.environ.get("STEAM_HOST_LIBRARY", "/mnt/host-steam")),
        help="Steam library root containing steamapps/",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    catalog = sub.add_parser("catalog", help="write RomM AppID descriptors")
    catalog.add_argument("--destination", type=Path, required=True)
    catalog.add_argument("--prune", action="store_true")
    stage = sub.add_parser("stage", help="stage an isolated container library")
    stage.add_argument(
        "--target",
        type=Path,
        default=Path("/config/.local/share/Steam"),
    )
    sub.add_parser("list", help="show discovered games without modifying anything")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        apps = discover(args.source.resolve())
        if args.command == "catalog":
            paths = write_catalog(apps, args.destination.resolve(), prune=args.prune)
            for path in paths:
                print(path)
            print(f"catalogued {len(paths)} Steam game(s)")
        elif args.command == "stage":
            paths = stage_library(apps, args.target.resolve())
            print(f"staged {len(paths)} Steam app manifest(s) read-only")
        else:
            for app in apps:
                kind = "tool" if app.is_tool else "game"
                print(f"{app.appid}\t{kind}\t{app.name}\t{app.install_path}")
    except SteamLibraryError as exc:
        print(f"steam-library: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
