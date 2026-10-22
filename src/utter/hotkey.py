"""A keyboard shortcut that works like the wake phrase, in any app."""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes

log = logging.getLogger("utter")

MODIFIERS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
NO_REPEAT = 0x4000
WM_HOTKEY = 0x0312
KEYS = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "pause": 0x13, "insert": 0x2D, "home": 0x24, "end": 0x23,
        "pageup": 0x21, "pagedown": 0x22, "scrolllock": 0x91, **{f"f{n}": 0x6F + n for n in range(1, 25)}}


def parse(spec: str) -> tuple[int, int] | None:
    """'ctrl+alt+space' -> (modifiers, virtual key), or None when it can't be used."""
    mods, key = 0, None
    for part in [p.strip().lower() for p in spec.split("+") if p.strip()]:
        if part in MODIFIERS:
            mods |= MODIFIERS[part]
        elif part in KEYS:
            key = KEYS[part]
        elif len(part) == 1 and part.isalnum():
            key = ord(part.upper())
        else:
            return None
    return (mods, key) if key is not None else None


def listen(spec: str, pressed: threading.Event) -> str:
    """Starts watching for the shortcut. Returns '' when it works, or why it doesn't."""
    keys = parse(spec)
    if keys is None:
        return f"can't understand the shortcut {spec!r}"
    started, outcome = threading.Event(), {"problem": ""}

    def run() -> None:
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, 1, keys[0] | NO_REPEAT, keys[1]):
            outcome["problem"] = f"{spec} is already used by another program"
            started.set()
            return
        started.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                pressed.set()

    threading.Thread(target=run, daemon=True).start()
    started.wait(2)
    if outcome["problem"]:
        log.warning("hotkey: %s", outcome["problem"])
    return outcome["problem"]
