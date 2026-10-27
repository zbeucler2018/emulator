#!/usr/bin/env python3
"""Translate the Retro Rewind RomM marker into a scoped Dolphin launch."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


MARKER_CONTENT = b"ROMM_RETRO_REWIND_LAUNCHER_V1\n"
DEFAULT_MARKER = "/romm/library/roms/Wii/Mario Kart Wii - Retro Rewind.dol"
DEFAULT_DESCRIPTOR = "/config/retro-rewind/launch/RetroRewind.json"
DEFAULT_DOLPHIN = "/usr/local/bin/dolphin-emu"
DEFAULT_SAVE_ROOT = "/config/.local/share/dolphin-emu/Wii/riivolution-save"
PAD_BINDINGS = {
    "Buttons/A": "`Button E`",
    "Buttons/B": "`Button S`",
    "Buttons/X": "`Button N`",
    "Buttons/Y": "`Button W`",
    "Buttons/Z": "`Shoulder L`",
    "Buttons/Start": "Start",
    "Main Stick/Up": "`Left Y+`",
    "Main Stick/Down": "`Left Y-`",
    "Main Stick/Left": "`Left X-`",
    "Main Stick/Right": "`Left X+`",
    "C-Stick/Up": "`Right Y+`",
    "C-Stick/Down": "`Right Y-`",
    "C-Stick/Left": "`Right X-`",
    "C-Stick/Right": "`Right X+`",
    "Triggers/L": "`Trigger L`",
    "Triggers/R": "`Trigger R`",
    "Triggers/L-Analog": "`Thumb L`",
    "Triggers/R-Analog": "`Thumb R`",
    "D-Pad/Up": "`Pad N`",
    "D-Pad/Down": "`Pad S`",
    "D-Pad/Left": "`Pad W`",
    "D-Pad/Right": "`Pad E`",
}


def _validate_descriptor(path: Path, save_root: Path) -> None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Retro Rewind descriptor is unavailable or invalid: {path}: {exc}") from exc
    if value.get("type") != "dolphin-game-mod-descriptor" or value.get("version") != 1:
        raise RuntimeError(f"unsupported Retro Rewind descriptor: {path}")
    if not Path(value.get("base-file", "")).is_file():
        raise RuntimeError(f"Retro Rewind base game is unavailable: {value.get('base-file')}")
    patches = value.get("riivolution", {}).get("patches", [])
    if len(patches) != 1:
        raise RuntimeError("Retro Rewind descriptor must contain exactly one Riivolution patch")
    patch = patches[0]
    if not Path(patch.get("xml", "")).is_file() or not Path(patch.get("root", "")).is_dir():
        raise RuntimeError("Retro Rewind assets are missing; run scripts/retro_rewind.py install")
    save_link = Path(patch["root"]) / "riivolution" / "save"
    if not save_link.is_symlink() or os.readlink(save_link) != str(save_root):
        raise RuntimeError(f"Retro Rewind save redirect is missing or unsafe: {save_link}")


def _replace_exec(args: list[str], marker: str, descriptor: str) -> tuple[list[str], bool]:
    rewritten = list(args)
    matched = False
    index = 0
    while index < len(rewritten):
        if rewritten[index] in ("-e", "--exec") and index + 1 < len(rewritten):
            if os.path.normpath(rewritten[index + 1]) == os.path.normpath(marker):
                rewritten[index + 1] = descriptor
                matched = True
            index += 2
            continue
        if rewritten[index].startswith("--exec="):
            value = rewritten[index].split("=", 1)[1]
            if os.path.normpath(value) == os.path.normpath(marker):
                rewritten[index] = f"--exec={descriptor}"
                matched = True
        index += 1
    return rewritten, matched


def _retro_config(backend: str, internal_resolution: int) -> list[str]:
    values = [
        f"GFX.Settings.InternalResolution={internal_resolution}",
        "GFX.Settings.AspectRatio=0",
        "GFX.Settings.ShaderCompilationMode=1",
        "GFX.Settings.WaitForShadersBeforeStarting=True",
        "GFX.Enhancements.MaxAnisotropy=4",
        "Dolphin.Core.EnableCheats=False",
        "Achievements.Achievements.Enabled=False",
        "Dolphin.Core.SIDevice0=6",
        "Dolphin.Core.SIDevice1=6",
        "Dolphin.Core.SIDevice2=0",
        "Dolphin.Core.SIDevice3=0",
    ]
    for pad_index in (0, 1):
        section = f"GCPad{pad_index + 1}"
        values.append(f"GCPad.{section}.Device=SDL/{pad_index}/Xbox 360 Controller")
        values.extend(f"GCPad.{section}.{key}={value}" for key, value in PAD_BINDINGS.items())
    result = [f"--video_backend={backend}"]
    for value in values:
        result.extend(("-C", value))
    return result


def build_command(argv: list[str], env: dict[str, str]) -> tuple[list[str], bool]:
    marker = env.get("RETRO_REWIND_MARKER", DEFAULT_MARKER)
    descriptor = env.get("RETRO_REWIND_DESCRIPTOR", DEFAULT_DESCRIPTOR)
    dolphin = env.get("DOLPHIN_FINAL_BIN", DEFAULT_DOLPHIN)
    rewritten, is_retro = _replace_exec(argv, marker, descriptor)
    if not is_retro:
        return [dolphin, *argv], False
    try:
        if Path(marker).read_bytes() != MARKER_CONTENT:
            raise RuntimeError(f"Retro Rewind marker has unexpected contents: {marker}")
    except OSError as exc:
        raise RuntimeError(f"Retro Rewind marker is unavailable: {marker}: {exc}") from exc
    save_root = Path(env.get("RETRO_REWIND_SAVE_ROOT", DEFAULT_SAVE_ROOT))
    _validate_descriptor(Path(descriptor), save_root)
    # The broker has just restored this game's Wii subtree. Create the link
    # target after restore so Riivolution's external save joins the same
    # per-user/per-ROM archive without sharing vanilla Mario Kart progress.
    save_root.mkdir(parents=True, exist_ok=True)
    backend = env.get("RETRO_REWIND_VIDEO_BACKEND", "Vulkan")
    try:
        internal_resolution = int(env.get("RETRO_REWIND_INTERNAL_RESOLUTION", "3"))
    except ValueError as exc:
        raise RuntimeError("RETRO_REWIND_INTERNAL_RESOLUTION must be an integer") from exc
    if internal_resolution not in range(1, 7):
        raise RuntimeError("RETRO_REWIND_INTERNAL_RESOLUTION must be between 1 and 6")
    return [dolphin, *rewritten, *_retro_config(backend, internal_resolution)], True


def main() -> int:
    try:
        command, _ = build_command(sys.argv[1:], dict(os.environ))
    except RuntimeError as exc:
        print(f"dolphin-retro-rewind-wrapper: {exc}", file=sys.stderr)
        return 2
    os.execvpe(command[0], command, os.environ)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
