"""python -m utter [run | setup | doctor | uninstall]"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
import threading

from . import settings as paths


def wait_for_exit(pid: int, seconds: float = 15) -> None:
    """Restart: let the old Utter quit (and free the microphone) before this one starts."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if handle:
        kernel32.WaitForSingleObject(handle, int(seconds * 1000))
        kernel32.CloseHandle(handle)


def run(after: int = 0) -> int:
    paths.STATE.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=paths.LOG, level=logging.INFO, format="%(asctime)s %(message)s", encoding="utf-8")
    log = logging.getLogger("utter")
    if after:
        wait_for_exit(after)

    # One copy only: two would fight over the microphone and the message box.
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\UtterVoiceForClaude")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        log.info("already running")
        return 0
    (paths.STATE / "app.pid").write_text(str(os.getpid()))
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # sharp text and true screen positions
    except Exception:
        pass

    from .app import Assistant
    from .ui import strip, tray

    settings = paths.load()
    assistant = Assistant(settings)

    def guarded() -> None:
        try:
            assistant.run()
        except Exception:
            log.exception("Utter stopped")
            assistant.show("problem", "Utter stopped. Open the log from the tray")

    threading.Thread(target=guarded, daemon=True).start()
    tray(settings)
    strip(settings)  # runs until Quit
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="utter", description="Hands-free voice for Claude on Windows.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "setup", "doctor", "uninstall"])
    parser.add_argument("--no-start", action="store_true", help="setup: don't start Utter at the end")
    parser.add_argument("--after", type=int, default=0, help=argparse.SUPPRESS)  # restart: wait for this process
    args = parser.parse_args()
    if args.command == "run":
        return run(args.after)
    from . import setup

    if args.command == "setup":
        return setup.install(start=not args.no_start)
    if args.command == "doctor":
        return setup.doctor()
    return setup.uninstall()


if __name__ == "__main__":
    sys.exit(main())
