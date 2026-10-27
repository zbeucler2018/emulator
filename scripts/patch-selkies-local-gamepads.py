#!/usr/bin/env python3
"""Preserve multiple local browser gamepads in a secured Selkies session.

Selkies 2.0 assigns a secured browser connection one collaboration controller
slot. Its frontend consequently rewrites every Gamepad API index from that
browser to the one collaboration slot, which makes two couch-co-op pads behave
as one. The server then rejects any other index from the host connection.

For the host/controller connection, keep the browser's physical gamepad index.
Remote multiplayer viewers remain pinned to their assigned collaboration slot.
The replacements are deliberately exact and fail loudly when upstream changes,
so a future WebStation upgrade cannot silently reintroduce the multiplexing.
"""

from __future__ import annotations

import argparse
from pathlib import Path


HOST_SLOT = "this.controllerSlot===null?this.playerIndex:this.controllerSlot-1"

JS_REPLACEMENTS = (
    (
        "connect",
        f"_gamepadConnected(e){{let t={HOST_SLOT};",
        "_gamepadConnected(e){let t=this.controllerSlot===null?this.playerIndex:"
        "this.isSharedMode?this.controllerSlot-1:e.gamepad.index;",
    ),
    (
        "disconnect",
        "_gamepadDisconnect(e){this.ongamepaddisconnected!==null&&"
        f"this.ongamepaddisconnected();let t={HOST_SLOT};",
        "_gamepadDisconnect(e){this.ongamepaddisconnected!==null&&"
        "this.ongamepaddisconnected();let t=this.controllerSlot===null?"
        "this.playerIndex:this.isSharedMode?this.controllerSlot-1:e.gamepad.index;",
    ),
    (
        "button",
        f"_gamepadButton(e,t,n){{let r={HOST_SLOT};",
        "_gamepadButton(e,t,n){let r=this.controllerSlot===null?this.playerIndex:"
        "this.isSharedMode?this.controllerSlot-1:e;",
    ),
    (
        "heartbeat",
        f"_gamepadHeartbeat(){{let e={HOST_SLOT};!Number.isInteger(e)||e<0||"
        "this.send(`js,h,`+e)}",
        "_gamepadHeartbeat(){let e=this.controllerSlot===null?[this.playerIndex]:"
        "this.isSharedMode?[this.controllerSlot-1]:Object.keys(this.gamepadManager.state);"
        "for(let t of e)Number.isInteger(+t)&&+t>=0&&this.send(`js,h,`+t)}",
    ),
    (
        "axis",
        f"_gamepadAxis(e,t,n){{let r={HOST_SLOT};",
        "_gamepadAxis(e,t,n){let r=this.controllerSlot===null?this.playerIndex:"
        "this.isSharedMode?this.controllerSlot-1:e;",
    ),
)

BACKEND_OLD = '''    if not msg.startswith("js,"):
        return False
    if slot is None:
'''
BACKEND_NEW = '''    if not msg.startswith("js,"):
        return False
    # The host browser may present several local couch-co-op pads. Remote
    # viewers remain restricted to their individually assigned slot below.
    if role == "controller":
        return False
    if slot is None:
'''


def patch_js_text(text: str) -> tuple[str, bool]:
    changed = False
    for label, old, new in JS_REPLACEMENTS:
        count = text.count(old)
        if count == 1:
            text = text.replace(old, new)
            changed = True
        elif count == 0 and text.count(new) == 1:
            continue
        else:
            raise RuntimeError(
                f"Selkies {label} patch expected one exact upstream occurrence; "
                f"found old={count}, patched={text.count(new)}"
            )
    return text, changed


def patch_backend_text(text: str) -> tuple[str, bool]:
    old_count = text.count(BACKEND_OLD)
    if old_count == 1:
        return text.replace(BACKEND_OLD, BACKEND_NEW), True
    if old_count == 0 and text.count(BACKEND_NEW) == 1:
        return text, False
    raise RuntimeError(
        "Selkies backend patch expected one exact upstream occurrence; "
        f"found old={old_count}, patched={text.count(BACKEND_NEW)}"
    )


def candidate_files(roots: list[Path]) -> list[Path]:
    files: set[Path] = set()
    for root in roots:
        if root.is_file():
            files.add(root)
            continue
        if not root.is_dir():
            raise FileNotFoundError(root)
        files.update(root.rglob("input_handler.py"))
        files.update(root.rglob("selkies-core*.js"))
    return sorted(files)


def patch_paths(roots: list[Path]) -> tuple[int, int]:
    backend_count = 0
    frontend_count = 0
    for path in candidate_files(roots):
        text = path.read_text()
        if path.name == "input_handler.py":
            patched, changed = patch_backend_text(text)
            backend_count += 1
        else:
            patched, changed = patch_js_text(text)
            frontend_count += 1
        if changed:
            path.write_text(patched)
        print(f"selkies local-gamepad patch: {'updated' if changed else 'already patched'} {path}")

    if backend_count != 1:
        raise RuntimeError(f"expected one Selkies input_handler.py, found {backend_count}")
    if frontend_count == 0:
        raise RuntimeError("no Selkies frontend bundles found")
    return backend_count, frontend_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", type=Path)
    args = parser.parse_args()
    backend_count, frontend_count = patch_paths(args.roots)
    print(
        f"selkies local-gamepad patch complete: backend={backend_count}, "
        f"frontend={frontend_count}"
    )


if __name__ == "__main__":
    main()
