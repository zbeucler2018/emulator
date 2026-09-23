#!/usr/bin/env python3
"""Expose existing RPCS3 installed-title folders to Webstation without copying.

The game library remains canonical and read-only. This script creates only
symlinks in Webstation's persistent config tree for folders that have the
installed-title layout <title>/USRDIR/EBOOT.BIN. Existing non-symlink paths
are always refused.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def installed_titles(library_ps3: Path) -> list[Path]:
    titles: list[Path] = []
    for category in sorted(library_ps3.iterdir()):
        if not category.is_dir():
            continue
        for title in sorted(category.iterdir()):
            if title.is_dir() and (title / "USRDIR" / "EBOOT.BIN").is_file():
                titles.append(title)
    return titles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library_ps3", type=Path, help="PS3 library directory")
    parser.add_argument("game_dir", type=Path, help="Webstation dev_hdd0/game directory")
    parser.add_argument(
        "--container-library-ps3",
        type=Path,
        default=Path("/romm/library/roms/PS3"),
        help="PS3 path as mounted inside Webstation",
    )
    parser.add_argument(
        "--replace-host-targets",
        action="store_true",
        help="replace only aliases made by older versions pointing at the host path",
    )
    parser.add_argument("--dry-run", action="store_true", help="report aliases without creating them")
    args = parser.parse_args()

    library = args.library_ps3.resolve()
    game_dir = args.game_dir.resolve()
    if not library.is_dir():
        parser.error(f"not a directory: {library}")
    if not game_dir.is_dir():
        parser.error(f"not a directory: {game_dir}")

    titles = installed_titles(library)
    conflicts: list[Path] = []
    planned: list[tuple[Path, Path]] = []
    replacements: list[tuple[Path, Path]] = []
    for title in titles:
        alias = game_dir / title.name
        container_target = args.container_library_ps3 / title.relative_to(library)
        if alias.is_symlink():
            if alias.readlink() == container_target:
                continue
            # This exact host target is what the first revision created. It
            # cannot resolve in the container, so replacing it is safe only
            # when the caller explicitly asks for this migration.
            if args.replace_host_targets and alias.readlink() == title:
                replacements.append((alias, container_target))
                continue
            conflicts.append(alias)
        elif alias.exists():
            conflicts.append(alias)
        else:
            planned.append((alias, container_target))
    if conflicts:
        print("refusing to replace existing installed-title paths:", file=sys.stderr)
        print("\n".join(str(path) for path in conflicts), file=sys.stderr)
        return 1

    print(
        f"found {len(titles)} installed titles; creating {len(planned)} aliases "
        f"and replacing {len(replacements)} managed aliases"
    )
    for alias, title in [*replacements, *planned]:
        print(f"{alias.name} -> {title}")
        if not args.dry_run:
            if alias.is_symlink():
                alias.unlink()
            os.symlink(title, alias, target_is_directory=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
