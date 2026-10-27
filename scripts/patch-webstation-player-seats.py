#!/usr/bin/env python3
"""Automatically give WebStation participants the first free gamepad slot.

WebStation's ``participant`` permission only makes a guest eligible for input;
the stock room leaves the guest unassigned until the host drags a numbered
gamepad onto their tile.  That is easy to miss and makes a RomM "Player"
invite look broken.  Assign participants to the first free virtual pad while
leaving ``readonly`` spectators unassigned.  The host can still rearrange or
remove assignments with the existing room controls.

The replacement is deliberately exact and idempotent.  A future pinned
WebStation update that changes this code fails the image build instead of
silently dropping the behavior.
"""

from __future__ import annotations

import argparse
from pathlib import Path


OLD_BLOCK = '''    viewer = {
        "token": secrets.token_urlsafe(16),
        "public_id": new_public_id(),
        "user_id": user.get("id"),
        "anonymous": anonymous,
        "last_seen": time.time(),
        "slot": None,
        "mk_control": False,
        "username": username or f"User-{random.randint(100, 999)}",
        "permission": permission,
    }
'''

NEW_BLOCK = '''    # A participant is a player, so make the common two-device flow work
    # without a hidden drag-and-drop step. Spectators remain input-disabled.
    occupied_slots = {SESSION.get("controller_slot")}
    occupied_slots.update(v.get("slot") for v in SESSION.get("viewers", []))
    automatic_slot = (
        next(
            (
                slot
                for slot in range(1, settings.GAMEPAD_SLOTS + 1)
                if slot not in occupied_slots
            ),
            None,
        )
        if permission == "participant"
        else None
    )

    viewer = {
        "token": secrets.token_urlsafe(16),
        "public_id": new_public_id(),
        "user_id": user.get("id"),
        "anonymous": anonymous,
        "last_seen": time.time(),
        "slot": automatic_slot,
        "mk_control": False,
        "username": username or f"User-{random.randint(100, 999)}",
        "permission": permission,
    }
'''


def first_available_slot(
    permission: str,
    controller_slot: int | None,
    viewer_slots: list[int | None],
    gamepad_slots: int = 4,
) -> int | None:
    """Reference implementation used by tests and the injected code above."""
    if permission != "participant":
        return None
    occupied = {controller_slot, *viewer_slots}
    return next((slot for slot in range(1, gamepad_slots + 1) if slot not in occupied), None)


def patch_text(text: str) -> tuple[str, bool]:
    old_count = text.count(OLD_BLOCK)
    if old_count == 1:
        return text.replace(OLD_BLOCK, NEW_BLOCK), True
    if old_count == 0 and text.count(NEW_BLOCK) == 1:
        return text, False
    raise RuntimeError(
        "WebStation player-seat patch expected one exact upstream occurrence; "
        f"found old={old_count}, patched={text.count(NEW_BLOCK)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_py", type=Path)
    args = parser.parse_args()

    text = args.session_py.read_text()
    patched, changed = patch_text(text)
    if changed:
        args.session_py.write_text(patched)
    print(
        "webstation player-seat patch: "
        f"{'updated' if changed else 'already patched'} {args.session_py}"
    )


if __name__ == "__main__":
    main()
