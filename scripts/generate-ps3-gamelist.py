#!/usr/bin/env python3
"""Create RomM's PS3 gamelist.xml from installed-game PARAM.SFO files.

This is deliberately metadata-only: it neither renames nor alters the game
directories.  The expected library shape is PS3/<category>/<game>/..., which
matches the PS3 filesystem rule in config/config.yml.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import tempfile
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement, indent


PSF_MAGIC = b"\x00PSF"
PSF_HEADER = struct.Struct("<4sIIII")
PSF_INDEX = struct.Struct("<HHIII")
UTF8_FORMAT = 0x0204

# A few installed titles report a data/DLC label in PARAM.SFO even though the
# directory contains the base game's executable. Entries can also name a
# verified standalone PKG. Keep these presentation-only corrections here; the
# serial and game files are never changed.
TITLE_OVERRIDES = {
    "digital_games/BLUS30464": ("Skate 3", "BLUS30464"),
    # The package's local header names content ID
    # UP0006-NPUB30569_00-DS1HDDNAEFS00001 (Dead Space, US PSN release).
    "digital_games/JpnzMoXYQxLVoDQuYjTLkRaBMTwvKkRUpTPFZPObbAVkNQgBbGqlAMtQmcChmbokRQeHvcnocHDqdrGNpbYVKYpuQXPBSSZurxive.pkg": (
        "Dead Space",
        "NPUB30569",
    ),
}


def read_sfo(path: Path) -> dict[str, str]:
    """Read UTF-8 string fields from a PS3 PARAM.SFO without external tools."""
    raw = path.read_bytes()
    if len(raw) < PSF_HEADER.size:
        raise ValueError("file is shorter than a PSF header")

    magic, _version, key_offset, data_offset, entries = PSF_HEADER.unpack_from(raw)
    if magic != PSF_MAGIC:
        raise ValueError("not a PSF file")

    values: dict[str, str] = {}
    for index in range(entries):
        offset = PSF_HEADER.size + index * PSF_INDEX.size
        if offset + PSF_INDEX.size > len(raw):
            raise ValueError("truncated PSF index")
        key_rel, value_format, value_len, _value_max_len, value_rel = PSF_INDEX.unpack_from(
            raw, offset
        )
        key_start = key_offset + key_rel
        key_end = raw.find(b"\0", key_start)
        if key_end < key_start:
            continue
        key = raw[key_start:key_end].decode("ascii", errors="ignore")
        if value_format != UTF8_FORMAT or not key:
            continue
        value_start = data_offset + value_rel
        value_end = min(value_start + value_len, len(raw))
        value = raw[value_start:value_end].rstrip(b"\0").decode("utf-8", errors="replace")
        values[key] = " ".join(value.split())
    return values


def boot_file(game_dir: Path) -> Path | None:
    """Return the supported executable for a folder title, if it has one."""
    # Digital RPCS3 installs and decrypted disc dumps use these two layouts.
    # A PARAM.SFO by itself can describe DLC or game-data and is not launchable.
    for candidate in (
        game_dir / "USRDIR" / "EBOOT.BIN",
        game_dir / "PS3_GAME" / "USRDIR" / "EBOOT.BIN",
        game_dir / "EBOOT.BIN",
    ):
        if candidate.is_file():
            return candidate
    return None


def find_games(platform_dir: Path) -> tuple[dict[Path, tuple[str, str]], int]:
    """Map launchable category/game directories to their title and PS3 serial."""
    games: dict[Path, tuple[str, str]] = {}
    metadata_only = 0
    # Do not recursively walk a full PS3 install: it can contain millions of
    # files on a network share. The library shape guarantees a title directory
    # immediately under each category. Digital installs keep PARAM.SFO in that
    # directory; disc dumps commonly place it in PS3_GAME one level below.
    for category_dir in sorted(platform_dir.iterdir()):
        if not category_dir.is_dir():
            continue
        for game_dir in sorted(category_dir.iterdir()):
            if not game_dir.is_dir():
                continue
            relative_game_dir = game_dir.relative_to(platform_dir)
            if boot_file(game_dir) is None:
                # Keep reporting only folders with metadata: unrelated helper
                # directories should not make the report noisy.
                if (game_dir / "PARAM.SFO").is_file() or (
                    game_dir / "PS3_GAME" / "PARAM.SFO"
                ).is_file():
                    metadata_only += 1
                continue
            candidates = (game_dir / "PARAM.SFO", game_dir / "PS3_GAME" / "PARAM.SFO")
            for sfo in candidates:
                if not sfo.is_file():
                    continue
                try:
                    fields = read_sfo(sfo)
                except (OSError, ValueError) as error:
                    print(f"warning: skipped {sfo}: {error}", file=sys.stderr)
                    continue
                title = fields.get("TITLE", "").strip()
                serial = fields.get("TITLE_ID", "").strip()
                if title:
                    title, serial = TITLE_OVERRIDES.get(
                        relative_game_dir.as_posix(), (title, serial)
                    )
                    games[relative_game_dir] = (title, serial)
                    break
    # Packages are valid RPCS3 installers. They have no PARAM.SFO until the
    # first launch installs them, so only explicitly verified package entries
    # belong in the local metadata sidecar.
    for relative_path, metadata in TITLE_OVERRIDES.items():
        path = Path(relative_path)
        if path.suffix.lower() == ".pkg" and (platform_dir / path).is_file():
            games[path] = metadata
    return games, metadata_only


def build_xml(games: dict[Path, tuple[str, str]]) -> ElementTree:
    root = Element("gameList")
    for game_dir, (title, serial) in sorted(games.items(), key=lambda item: item[1][0].casefold()):
        game = SubElement(root, "game")
        SubElement(game, "path").text = f"./{game_dir.as_posix()}"
        SubElement(game, "name").text = title
        SubElement(game, "sortname").text = title
        if serial:
            SubElement(game, "desc").text = f"PlayStation 3 title ID: {serial}"
    tree = ElementTree(root)
    indent(tree, space="  ")
    return tree


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform_dir", type=Path, help="PS3 platform directory")
    parser.add_argument("--output", type=Path, help="defaults to <platform_dir>/gamelist.xml")
    parser.add_argument("--force", action="store_true", help="replace an existing manifest")
    parser.add_argument("--dry-run", action="store_true", help="report entries without writing")
    args = parser.parse_args()

    platform_dir = args.platform_dir.resolve()
    if not platform_dir.is_dir():
        parser.error(f"not a directory: {platform_dir}")
    output = args.output or platform_dir / "gamelist.xml"
    games, metadata_only = find_games(platform_dir)
    if not games:
        print("no titled PARAM.SFO files found", file=sys.stderr)
        return 1

    print(f"found {len(games)} launchable PS3 titles")
    if metadata_only:
        print(f"skipped {metadata_only} metadata-only PS3 folders")
    if args.dry_run:
        for path, (title, serial) in sorted(games.items()):
            print(f"{path}: {title} ({serial or 'no title ID'})")
        return 0
    if output.exists() and not args.force:
        parser.error(f"refusing to overwrite existing {output}; use --force after review")

    tree = build_xml(games)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=output.parent, delete=False) as temp:
        temp_path = Path(temp.name)
        tree.write(temp, encoding="utf-8", xml_declaration=True)
        temp.write(b"\n")
    os.replace(temp_path, output)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
