#!/usr/bin/env python3
"""Install and maintain Retro Rewind without making Wheel Wizard a runtime dependency.

The official Wheel Wizard endpoints remain the source of truth.  Releases are
downloaded and validated in a staging directory, then published by atomically
replacing a ``current`` symlink.  The previous release is retained for rollback.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable
from xml.etree import ElementTree


INSTALL_URL = "https://update.rwfc.net/RetroRewind/RetroRewindInstall.txt"
VERSIONS_URL = "https://update.rwfc.net/RetroRewind/RetroRewindVersion.txt"
ALLOWED_DOWNLOAD_HOSTS = {"update.rwfc.net", "cdn.update.rwfc.net"}
SUPPORTED_EXTENSIONS = {".iso", ".wbfs", ".rvz", ".wia", ".gcz", ".ciso"}
SUPPORTED_GAME_IDS = {"RMCE01": "NTSC-U", "RMCP01": "PAL", "RMCJ01": "NTSC-J"}
SUPPORTED_REVISIONS = {0}
MARKER_CONTENT = b"ROMM_RETRO_REWIND_LAUNCHER_V1\n"
MARKER_NAME = "Mario Kart Wii - Retro Rewind.dol"
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
MAX_ARCHIVE_FILES = 100_000
MAX_UNCOMPRESSED_BYTES = 32 * 1024**3


class RetroRewindError(RuntimeError):
    """A safe, user-facing failure."""


@dataclass(frozen=True)
class RomInfo:
    path: str
    container_path: str
    format: str
    game_id: str
    region: str
    revision: int
    size: int


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    archive_url: str
    archive_sha256: str
    archive_size: int
    installed_at: str
    rom: RomInfo
    source: str = "official Wheel Wizard Retro Rewind endpoint"


def _version_key(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.fullmatch(value.strip())
    if not match:
        raise RetroRewindError(f"invalid Retro Rewind version: {value!r}")
    return tuple(int(part) for part in match.groups())


def _read_url(url: str, timeout: int = 30) -> str:
    _validate_official_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "romm-retro-rewind/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise RetroRewindError(f"could not read {url}: {exc}") from exc


def _validate_official_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
        raise RetroRewindError(f"refusing non-official download URL: {url}")


def latest_release() -> tuple[str, str]:
    archive_url = _read_url(INSTALL_URL).strip()
    _validate_official_url(archive_url)
    versions: list[tuple[tuple[int, int, int], str, str]] = []
    for line in _read_url(VERSIONS_URL).splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) < 2 or not VERSION_RE.fullmatch(parts[0]):
            continue
        _validate_official_url(parts[1])
        versions.append((_version_key(parts[0]), parts[0], parts[1]))
    if not versions:
        raise RetroRewindError("the official version manifest contained no versions")
    _, version, _ = max(versions)
    archive_name = Path(urllib.parse.urlparse(archive_url).path).name
    if version not in archive_name:
        raise RetroRewindError(
            f"official install archive {archive_name!r} does not match latest version {version}"
        )
    return version, archive_url


def _candidate_roms(rom_library: Path) -> list[Path]:
    wii_dir = rom_library / "Wii"
    if not wii_dir.is_dir():
        raise RetroRewindError(f"Wii library does not exist: {wii_dir}")
    candidates = [
        path
        for path in wii_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
        and "mario kart wii" in path.name.lower()
    ]
    return sorted(candidates, key=lambda path: (len(path.parts), path.name.lower()))


def _native_header(path: Path) -> tuple[str, int] | None:
    offset = {".iso": 0, ".wbfs": 0x200}.get(path.suffix.lower())
    if offset is None:
        return None
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            header = handle.read(8)
    except OSError as exc:
        raise RetroRewindError(f"could not read ROM header from {path}: {exc}") from exc
    if len(header) != 8:
        raise RetroRewindError(f"ROM is too short to contain a Wii disc header: {path}")
    try:
        game_id = header[:6].decode("ascii")
    except UnicodeDecodeError as exc:
        raise RetroRewindError(f"ROM has a non-ASCII game ID: {path}") from exc
    return game_id, header[7]


def _dolphin_header(
    path: Path,
    rom_library: Path,
    container_library: Path,
    container: str,
    dolphin_tool: str | None,
) -> dict[str, object]:
    if dolphin_tool:
        command = [dolphin_tool, "header", "-j", "-i", str(path)]
    else:
        try:
            relative = path.resolve().relative_to(rom_library.resolve())
        except ValueError as exc:
            raise RetroRewindError(f"ROM is outside the configured library: {path}") from exc
        command = [
            "docker",
            "exec",
            container,
            "dolphin-tool",
            "header",
            "-j",
            "-i",
            str(container_library / relative),
        ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise RetroRewindError(
            "Dolphin could not inspect the compressed ROM; keep WebStation running "
            "or pass --dolphin-tool"
        ) from exc


def inspect_rom(
    path: Path,
    rom_library: Path,
    container_library: Path,
    container: str,
    dolphin_tool: str | None = None,
) -> RomInfo:
    path = path.resolve()
    if not path.is_file():
        raise RetroRewindError(f"ROM does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise RetroRewindError(
            f"unsupported Mario Kart Wii format {suffix or '<none>'}; expected one of "
            + ", ".join(sorted(SUPPORTED_EXTENSIONS))
        )
    native = _native_header(path)
    if native:
        game_id, revision = native
        region = SUPPORTED_GAME_IDS.get(game_id, "unknown")
    else:
        header = _dolphin_header(
            path, rom_library, container_library, container, dolphin_tool
        )
        game_id = str(header.get("game_id", ""))
        revision = int(header.get("revision", -1))
        region = str(header.get("region", SUPPORTED_GAME_IDS.get(game_id, "unknown")))
    if game_id not in SUPPORTED_GAME_IDS:
        raise RetroRewindError(
            f"{path.name} is {game_id or 'an unknown title'}, not a supported "
            f"Mario Kart Wii disc ({', '.join(sorted(SUPPORTED_GAME_IDS))})"
        )
    if revision not in SUPPORTED_REVISIONS:
        raise RetroRewindError(
            f"unsupported Mario Kart Wii revision {revision} for {game_id}; "
            f"supported revisions: {sorted(SUPPORTED_REVISIONS)}"
        )
    relative = path.relative_to(rom_library.resolve())
    return RomInfo(
        path=str(path),
        container_path=str(container_library / relative),
        format=suffix.lstrip("."),
        game_id=game_id,
        region=region,
        revision=revision,
        size=path.stat().st_size,
    )


def discover_rom(
    rom_library: Path,
    container_library: Path,
    container: str,
    explicit: Path | None = None,
    dolphin_tool: str | None = None,
) -> RomInfo:
    candidates = [explicit] if explicit else _candidate_roms(rom_library)
    if not candidates:
        raise RetroRewindError("no Mario Kart Wii backup was found")
    valid: list[RomInfo] = []
    failures: list[str] = []
    for candidate in candidates:
        assert candidate is not None
        try:
            valid.append(
                inspect_rom(
                    candidate,
                    rom_library,
                    container_library,
                    container,
                    dolphin_tool,
                )
            )
        except RetroRewindError as exc:
            failures.append(str(exc))
    if len(valid) == 1:
        return valid[0]
    if len(valid) > 1:
        names = "\n  ".join(info.path for info in valid)
        raise RetroRewindError(f"multiple compatible backups found; select one with --rom:\n  {names}")
    raise RetroRewindError("no compatible Mario Kart Wii backup found:\n  " + "\n  ".join(failures))


def _download(url: str, destination: Path) -> tuple[str, int]:
    _validate_official_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "romm-retro-rewind/1"})
    digest = hashlib.sha256()
    size = 0
    try:
        with urllib.request.urlopen(request, timeout=120) as response, destination.open("xb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            output.flush()
            os.fsync(output.fileno())
    except OSError as exc:
        raise RetroRewindError(f"Retro Rewind download failed: {exc}") from exc
    return digest.hexdigest(), size


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _safe_members(archive: zipfile.ZipFile) -> Iterable[tuple[zipfile.ZipInfo, Path]]:
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_FILES:
        raise RetroRewindError(f"archive contains too many entries ({len(infos)})")
    total = sum(info.file_size for info in infos)
    if total > MAX_UNCOMPRESSED_BYTES:
        raise RetroRewindError(f"archive expands beyond the {MAX_UNCOMPRESSED_BYTES} byte limit")
    seen: set[str] = set()
    for info in infos:
        name = info.filename.replace("\\", "/")
        pure = PurePosixPath(name)
        if not name or pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise RetroRewindError(f"archive contains an unsafe path: {info.filename!r}")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise RetroRewindError(f"archive contains a symbolic link: {info.filename!r}")
        normalized = str(pure)
        if normalized in seen:
            raise RetroRewindError(f"archive contains a duplicate path: {normalized}")
        seen.add(normalized)
        yield info, Path(*pure.parts)


def extract_archive(archive_path: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info, relative in _safe_members(archive):
                target = destination / relative
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RetroRewindError(f"invalid or corrupt Retro Rewind archive: {exc}") from exc


def validate_release(release_dir: Path, expected_version: str | None = None) -> str:
    version_path = release_dir / "RetroRewind6" / "version.txt"
    xml_path = release_dir / "riivolution" / "RetroRewind6.xml"
    code_path = release_dir / "RetroRewind6" / "Binaries" / "Code.pul"
    loader_path = release_dir / "RetroRewind6" / "Binaries" / "Loader.pul"
    missing = [
        str(path.relative_to(release_dir))
        for path in (version_path, xml_path, code_path, loader_path)
        if not path.is_file()
    ]
    if missing:
        raise RetroRewindError("Retro Rewind assets are incomplete; missing: " + ", ".join(missing))
    version = version_path.read_text(encoding="utf-8").strip()
    _version_key(version)
    if expected_version and version != expected_version:
        raise RetroRewindError(
            f"archive reports Retro Rewind {version}, expected {expected_version}"
        )
    if code_path.stat().st_size < 100_000:
        raise RetroRewindError("Retro Rewind Code.pul is implausibly small")
    for relative in ("Tracks", "CT/Tracks", "Character", "strm", "Assets", "Language"):
        asset_dir = release_dir / "RetroRewind6" / relative
        if not asset_dir.is_dir() or not any(path.is_file() for path in asset_dir.rglob("*")):
            raise RetroRewindError(f"Retro Rewind asset directory is missing or empty: {relative}")
    try:
        xml_root = ElementTree.parse(xml_path).getroot()
    except (OSError, ElementTree.ParseError) as exc:
        raise RetroRewindError(f"RetroRewind6.xml is invalid: {exc}") from exc
    if xml_root.tag.lower().split("}")[-1] != "wiidisc":
        raise RetroRewindError("RetroRewind6.xml is not a Riivolution wiidisc document")
    if "Retro Rewind" not in xml_path.read_text(encoding="utf-8", errors="replace"):
        raise RetroRewindError("RetroRewind6.xml does not define the Retro Rewind section")
    return version


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_descriptor(install_root: Path, container_root: Path, rom: RomInfo) -> Path:
    descriptor = {
        "base-file": rom.container_path,
        "display-name": "Mario Kart Wii: Retro Rewind",
        "riivolution": {
            "patches": [
                {
                    "options": [
                        {"choice": 1, "option-name": "Pack", "section-name": "Retro Rewind"},
                        {"choice": 0, "option-name": "My Stuff", "section-name": "Retro Rewind"},
                    ],
                    "root": str(container_root / "current"),
                    "xml": str(container_root / "current" / "riivolution" / "RetroRewind6.xml"),
                }
            ]
        },
        "type": "dolphin-game-mod-descriptor",
        "version": 1,
    }
    path = install_root / "launch" / "RetroRewind.json"
    _write_json_atomic(path, descriptor)
    return path


def wire_save_redirect(release_dir: Path, container_save_root: Path) -> Path:
    """Redirect Riivolution saves into WebStation's broker-managed Wii tree.

    The link uses container coordinates. It is expected to look dangling on
    the host and to resolve below ``/config`` inside WebStation.
    """
    save_link = release_dir / "riivolution" / "save"
    target = str(container_save_root)
    if save_link.is_symlink():
        if os.readlink(save_link) != target:
            raise RetroRewindError(
                f"save redirect {save_link} points to {os.readlink(save_link)!r}, expected {target!r}"
            )
        return save_link
    if save_link.exists():
        raise RetroRewindError(f"refusing to replace the pack's existing save path: {save_link}")
    save_link.symlink_to(target, target_is_directory=True)
    return save_link


def _replace_symlink(link: Path, target: str) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    temporary = link.with_name(f".{link.name}.{os.getpid()}.tmp")
    try:
        temporary.symlink_to(target)
        os.replace(temporary, link)
    finally:
        if temporary.is_symlink():
            temporary.unlink()


def _current_version(install_root: Path) -> str | None:
    current = install_root / "current"
    if not current.is_symlink():
        return None
    try:
        return validate_release(current.resolve())
    except (OSError, RetroRewindError):
        return None


def _assert_no_game_session(container: str) -> None:
    try:
        result = subprocess.run(
            ["docker", "exec", container, "pgrep", "-x", "dolphin-emu"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RetroRewindError(
            f"could not verify that Dolphin is idle in {container}: {exc}"
        ) from exc
    if result.returncode == 0:
        raise RetroRewindError("Dolphin is running; updates and rollback are disabled during game sessions")
    if result.returncode not in (1,):
        raise RetroRewindError(
            f"could not verify Dolphin session state in {container}: {result.stderr.strip()}"
        )


def _publish_marker(rom_library: Path, dry_run: bool) -> Path:
    marker = rom_library / "Wii" / MARKER_NAME
    if marker.exists():
        if marker.read_bytes() != MARKER_CONTENT:
            raise RetroRewindError(f"refusing to overwrite an unrelated launcher marker: {marker}")
        return marker
    if dry_run:
        return marker
    temporary = marker.with_name(f".{marker.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(MARKER_CONTENT)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, marker)
    return marker


def install(args: argparse.Namespace) -> None:
    rom_library = args.rom_library.resolve()
    rom = discover_rom(
        rom_library,
        args.container_library,
        args.container,
        args.rom,
        args.dolphin_tool,
    )
    if args.archive:
        archive_path = args.archive.resolve()
        if not archive_path.is_file():
            raise RetroRewindError(f"archive does not exist: {archive_path}")
        digest, archive_size = _hash_file(archive_path)
        version = args.version or ""
        archive_url = f"file://{archive_path}"
        if not version:
            with tempfile.TemporaryDirectory(prefix="rr-inspect-") as temporary:
                extract_archive(archive_path, Path(temporary))
                version = validate_release(Path(temporary))
    else:
        version, archive_url = latest_release()
        digest = ""
        archive_size = 0
    _version_key(version)
    current_version = _current_version(args.install_root)
    plan = {
        "action": "install",
        "current_version": current_version,
        "target_version": version,
        "archive": archive_url,
        "install_root": str(args.install_root),
        "rom": asdict(rom),
        "marker": str(rom_library / "Wii" / MARKER_NAME),
    }
    if args.dry_run:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return
    _assert_no_game_session(args.container)
    args.install_root.mkdir(parents=True, exist_ok=True)
    releases = args.install_root / "releases"
    releases.mkdir(exist_ok=True)
    release_dir = releases / version
    if release_dir.exists():
        validate_release(release_dir, version)
        wire_save_redirect(release_dir, args.container_save_root)
        manifest_path = release_dir / "romm-install.json"
        if manifest_path.is_file():
            try:
                installed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                digest = str(installed_manifest["archive_sha256"])
                archive_size = int(installed_manifest["archive_size"])
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RetroRewindError(f"installed provenance is invalid: {manifest_path}: {exc}") from exc
        if args.sha256 and digest.lower() != args.sha256.lower():
            raise RetroRewindError(
                f"installed archive checksum mismatch: got {digest}, expected {args.sha256.lower()}"
            )
    else:
        with tempfile.TemporaryDirectory(prefix=".retro-rewind-stage-", dir=args.install_root) as temporary:
            stage = Path(temporary)
            if args.archive:
                staged_archive = archive_path
            else:
                staged_archive = stage / "download.zip"
                digest, archive_size = _download(archive_url, staged_archive)
            if args.sha256 and digest.lower() != args.sha256.lower():
                raise RetroRewindError(
                    f"archive checksum mismatch: got {digest}, expected {args.sha256.lower()}"
                )
            extracted = stage / "extracted"
            extracted.mkdir()
            extract_archive(staged_archive, extracted)
            validate_release(extracted, version)
            wire_save_redirect(extracted, args.container_save_root)
            release_info = ReleaseInfo(
                version=version,
                archive_url=archive_url,
                archive_sha256=digest,
                archive_size=archive_size,
                installed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                rom=rom,
            )
            _write_json_atomic(extracted / "romm-install.json", asdict(release_info))
            os.replace(extracted, release_dir)
    old_target = os.readlink(args.install_root / "current") if (args.install_root / "current").is_symlink() else None
    new_target = f"releases/{version}"
    if old_target and old_target != new_target:
        _replace_symlink(args.install_root / "previous", old_target)
    _replace_symlink(args.install_root / "current", new_target)
    descriptor = write_descriptor(args.install_root, args.container_root, rom)
    marker = _publish_marker(rom_library, dry_run=False)
    state = {**plan, "archive_sha256": digest, "descriptor": str(descriptor), "marker": str(marker)}
    _write_json_atomic(args.install_root / "state.json", state)
    print(json.dumps(state, indent=2, sort_keys=True))


def rollback(args: argparse.Namespace) -> None:
    current = args.install_root / "current"
    if not current.is_symlink():
        raise RetroRewindError("Retro Rewind has no active release to roll back")
    old_target = os.readlink(current)
    if args.version:
        target = f"releases/{args.version}"
    else:
        previous = args.install_root / "previous"
        if not previous.is_symlink():
            raise RetroRewindError("no previous Retro Rewind release is recorded")
        target = os.readlink(previous)
    validate_release((args.install_root / target).resolve())
    if args.dry_run:
        print(json.dumps({"action": "rollback", "from": old_target, "to": target}, indent=2))
        return
    _assert_no_game_session(args.container)
    _replace_symlink(current, target)
    _replace_symlink(args.install_root / "previous", old_target)
    print(json.dumps({"action": "rollback", "from": old_target, "to": target}, indent=2))


def status(args: argparse.Namespace) -> None:
    installed = _current_version(args.install_root)
    latest: str | None = None
    archive_url: str | None = None
    if args.online:
        latest, archive_url = latest_release()
    result = {
        "installed_version": installed,
        "latest_version": latest,
        "update_available": bool(installed and latest and _version_key(latest) > _version_key(installed)),
        "archive_url": archive_url,
        "current": str((args.install_root / "current").resolve()) if installed else None,
        "descriptor_valid": (args.install_root / "launch" / "RetroRewind.json").is_file(),
        "marker_valid": (args.rom_library / "Wii" / MARKER_NAME).is_file()
        and (args.rom_library / "Wii" / MARKER_NAME).read_bytes() == MARKER_CONTENT,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom-library", type=Path, default=Path("/mnt/games/Sophia/games"))
    parser.add_argument("--install-root", type=Path, default=Path("/srv/emulator/retro-rewind"))
    parser.add_argument("--container-library", type=Path, default=Path("/romm/library/roms"))
    parser.add_argument("--container-root", type=Path, default=Path("/config/retro-rewind"))
    parser.add_argument(
        "--container-save-root",
        type=Path,
        default=Path("/config/.local/share/dolphin-emu/Wii/riivolution-save"),
    )
    parser.add_argument("--container", default="emulator-romm-webstation-1")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser("install", help="install or atomically update the official pack")
    install_parser.add_argument("--rom", type=Path)
    install_parser.add_argument("--dolphin-tool")
    install_parser.add_argument("--archive", type=Path, help="use a previously downloaded official archive")
    install_parser.add_argument("--version", help="expected version when using --archive")
    install_parser.add_argument("--sha256", help="require this archive SHA-256")
    install_parser.add_argument("--dry-run", action="store_true")
    install_parser.set_defaults(func=install)

    rollback_parser = subparsers.add_parser("rollback", help="atomically select the previous retained release")
    rollback_parser.add_argument("--version")
    rollback_parser.add_argument("--dry-run", action="store_true")
    rollback_parser.set_defaults(func=rollback)

    status_parser = subparsers.add_parser("status", help="validate local state")
    status_parser.add_argument("--online", action="store_true", help="also query the official latest version")
    status_parser.set_defaults(func=status)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except RetroRewindError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
