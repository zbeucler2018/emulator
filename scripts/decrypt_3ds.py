#!/usr/bin/env python3
"""Safely translate matiffeder's Batch CIA 3DS Decryptor to Python.

This is a wrapper around the same external utilities used by the original
Windows batch file: ``decrypt``, ``ctrtool``, and ``makerom``.  It deliberately
does not include keys, obtain keys, or download games/tools.  Use only with
your own dumped system material and games.

The original script works in-place and removes every ``*.ncch`` it finds.  This
version instead stages each input in a temporary directory and writes only the
final converted files to an explicitly chosen output directory.  It never
changes source ROMs.  Preview is the default; passing ``--execute`` is required
before any external conversion program can run.

Examples (neither command is run by this module unless --execute is supplied):

  scripts/decrypt_3ds.py /path/to/roms --output-dir /path/to/decrypted
  scripts/decrypt_3ds.py /path/to/roms --output-dir /path/to/decrypted --execute
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TITLE_BASE = "00040000"
TITLE_PATCH = "0004000e"
TITLE_DLC = "0004008c"

# Names emitted by the legacy ``decrypt`` utility and the partition numbers the
# original batch file assigned to them.
CCI_PARTITIONS = {
    "Main": 0,
    "Manual": 1,
    "DownloadPlay": 2,
    "Partition4": 3,
    "Partition5": 4,
    "Partition6": 5,
    "N3DSUpdateData": 6,
    "UpdateData": 7,
}


class ConversionError(RuntimeError):
    """Raised when a converter cannot produce the expected intermediate data."""


@dataclass(frozen=True)
class Plan:
    source: Path
    kind: str
    output: Path
    title_kind: str | None = None


def run(command: list[str], *, cwd: Path, execute: bool) -> subprocess.CompletedProcess[str] | None:
    """Print a command; run it only after the user explicitly opts in."""
    printable = " ".join(repr(part) for part in command)
    print(f"  $ (cd {cwd!s} && {printable})")
    if not execute:
        return None
    return subprocess.run(command, cwd=cwd, text=True, check=True)


def ensure_tools(execute: bool) -> None:
    if not execute:
        return
    missing = [tool for tool in ("decrypt", "ctrtool", "makerom") if shutil.which(tool) is None]
    if missing:
        raise ConversionError(
            "required converter tools are not on PATH: " + ", ".join(missing)
        )


def ncch_files(workdir: Path, stem: str) -> list[Path]:
    return sorted(workdir.glob(f"{stem}.*.ncch"))


def cci_inputs(parts: Iterable[Path], stem: str) -> list[str]:
    """Recreate the original batch file's named CCI partition mapping."""
    inputs: list[str] = []
    for part in parts:
        name = part.name
        prefix = f"{stem}."
        if not name.startswith(prefix) or not name.endswith(".ncch"):
            continue
        label = name[len(prefix) : -len(".ncch")]
        partition = CCI_PARTITIONS.get(label)
        if partition is not None:
            inputs.extend(["-i", f"{part}:{partition}:{partition}"])
    if not inputs:
        raise ConversionError("decrypt produced no recognized CCI NCCH partitions")
    return inputs


def tmd_text(source: Path, *, execute: bool) -> str:
    """Return ctrtool's TMD output without using a shell redirection."""
    print(f"  $ ctrtool -tmd {source!s}")
    if not execute:
        return ""
    result = subprocess.run(
        ["ctrtool", "-tmd", str(source)], text=True, capture_output=True, check=True
    )
    return result.stdout


def cia_title_kind(tmd: str) -> str | None:
    lower = tmd.lower()
    if TITLE_BASE in lower:
        return "base"
    if TITLE_PATCH in lower:
        return "patch"
    if TITLE_DLC in lower:
        return "dlc"
    return None


def cia_inputs(parts: list[Path], stem: str, tmd: str) -> list[str]:
    """Build makerom inputs, retaining the legacy script's content-ID mapping."""
    ids = [int(value, 16) for value in re.findall(r"Content id[^0-9a-fA-F]*([0-9a-fA-F]{8})", tmd)]
    inputs: list[str] = []
    for index, part in enumerate(parts):
        # The old script uses sequential .ncch names and, where present, the
        # content ID from ctrtool's TMD listing.  Fall back to the partition
        # index when a particular ctrtool version omits that field.
        match = re.fullmatch(re.escape(stem) + r"\.(\d+)\.ncch", part.name)
        partition = int(match.group(1)) if match else index
        content_id = ids[index] if index < len(ids) else partition
        inputs.extend(["-i", f"{part}:{partition}:{content_id}"])
    if not inputs:
        raise ConversionError("decrypt produced no CIA NCCH partitions")
    return inputs


def stage_source(source: Path, workdir: Path) -> Path:
    staged = workdir / source.name
    # A symlink avoids duplicating multi-gigabyte ROMs while leaving sources
    # read-only to this workflow.
    staged.symlink_to(source)
    return staged


def ensure_output_available(output: Path, *, execute: bool) -> None:
    """Avoid replacing a prior decrypted result during an execute run."""
    if execute and output.exists():
        raise ConversionError(f"refusing to overwrite existing output: {output}")


def convert_3ds(source: Path, output_dir: Path, *, execute: bool) -> Plan:
    output = output_dir / f"{source.stem}-decrypted.cci"
    ensure_output_available(output, execute=execute)
    plan = Plan(source=source, kind="cci", output=output)
    print(f"3DS: {source.name} -> {output.name}")
    with tempfile.TemporaryDirectory(prefix="romm-3ds-decrypt-") as temporary:
        workdir = Path(temporary)
        staged = stage_source(source, workdir)
        run(["decrypt", str(staged)], cwd=workdir, execute=execute)
        if execute:
            parts = ncch_files(workdir, source.stem)
            command = [
                "makerom", "-f", "cci", "-ignoresign", "-target", "p", "-o", str(output),
                *cci_inputs(parts, source.stem),
            ]
            run(command, cwd=workdir, execute=True)
            if not output.is_file() or output.stat().st_size == 0:
                raise ConversionError(f"makerom did not create {output}")
        else:
            print("  $ decrypt '<source>'  # produces <stem>.*.ncch in a private temp directory")
            print("  $ makerom -f cci -ignoresign -target p -o '<output>' -i '<partition>:N:N' ...")
    return plan


def convert_cia(source: Path, output_dir: Path, *, execute: bool) -> Plan | None:
    tmd = tmd_text(source, execute=execute)
    title_kind = cia_title_kind(tmd) if execute else None
    if execute and title_kind is None:
        print(f"Skipping {source.name}: not a base game, update, or DLC TMD")
        return None

    suffix = {"base": "-decrypted.cci", "patch": " (Patch)-decrypted.cia", "dlc": " (DLC)-decrypted.cia"}
    output = output_dir / f"{source.stem}{suffix[title_kind or 'base']}"
    ensure_output_available(output, execute=execute)
    plan = Plan(source=source, kind="cia", output=output, title_kind=title_kind)
    label = title_kind or "base/patch/DLC (determined during --execute)"
    print(f"CIA ({label}): {source.name} -> {output.name}")

    with tempfile.TemporaryDirectory(prefix="romm-3ds-decrypt-") as temporary:
        workdir = Path(temporary)
        staged = stage_source(source, workdir)
        run(["decrypt", str(staged)], cwd=workdir, execute=execute)
        if execute:
            parts = ncch_files(workdir, source.stem)
            inputs = cia_inputs(parts, source.stem, tmd)
            if title_kind == "base":
                intermediate = workdir / f"{source.stem}-decfirst.cia"
                run(
                    ["makerom", "-f", "cia", "-ignoresign", "-target", "p", "-o", str(intermediate), *inputs],
                    cwd=workdir,
                    execute=True,
                )
                run(["makerom", "-ciatocci", str(intermediate), "-o", str(output)], cwd=workdir, execute=True)
            else:
                extra = ["-dlc"] if title_kind == "dlc" else []
                run(
                    ["makerom", "-f", "cia", *extra, "-ignoresign", "-target", "p", "-o", str(output), *inputs],
                    cwd=workdir,
                    execute=True,
                )
            if not output.is_file() or output.stat().st_size == 0:
                raise ConversionError(f"makerom did not create {output}")
        else:
            print("  $ ctrtool -tmd '<source>'  # classifies base game vs patch/DLC")
            print("  $ decrypt '<source>'  # produces <stem>.*.ncch in a private temp directory")
            print("  $ makerom ...  # writes only the final output file")
    return plan


def sources(directory: Path) -> Iterable[Path]:
    for extension in ("*.3ds", "*.3DS", "*.cia", "*.CIA"):
        yield from sorted(directory.glob(extension))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path, help="directory containing .3ds and/or .cia files")
    parser.add_argument("--output-dir", type=Path, required=True, help="directory for decrypted outputs")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="run decrypt/ctrtool/makerom; without this flag only a safe preview is printed",
    )
    args = parser.parse_args()

    if not args.input_dir.is_dir():
        parser.error(f"input directory does not exist: {args.input_dir}")
    if args.output_dir.resolve() == args.input_dir.resolve():
        parser.error("--output-dir must differ from input_dir to protect source ROMs")
    if args.execute:
        args.output_dir.mkdir(parents=True, exist_ok=True)
    else:
        print("DRY RUN: no converter, ROM, or output file will be touched. Add --execute to run.")
    ensure_tools(args.execute)

    try:
        plans: list[Plan] = []
        for source in sources(args.input_dir):
            if "decrypted" in source.stem.casefold():
                print(f"Skipping already-labelled decrypted file: {source.name}")
                continue
            if source.suffix.casefold() == ".3ds":
                plans.append(convert_3ds(source, args.output_dir, execute=args.execute))
            else:
                plan = convert_cia(source, args.output_dir, execute=args.execute)
                if plan is not None:
                    plans.append(plan)
    except (ConversionError, subprocess.CalledProcessError) as error:
        print(f"conversion failed: {error}", file=sys.stderr)
        return 1

    print(f"Planned/created {len(plans)} output file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
