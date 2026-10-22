"""Typing into the Claude desktop app's message box.

Windows UI Automation shows the box as an Edit control named "Prompt" inside the window
titled "Claude". Parley remembers where on screen you last clicked one, then clicks there
and pastes. Every UI Automation call runs on one thread, because COM needs that.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time

from . import settings as paths

log = logging.getLogger("parley")


def _saved_place():
    try:
        return tuple(json.loads(paths.BOX_PLACE.read_text()))
    except Exception:
        return None


def claude_window() -> int:
    import win32gui

    found = []

    def visit(hwnd, _):
        if (
            win32gui.IsWindowVisible(hwnd)
            and win32gui.GetWindowText(hwnd) == "Claude"
            and win32gui.GetClassName(hwnd) == "Chrome_WidgetWin_1"
        ):
            found.append(hwnd)

    win32gui.EnumWindows(visit, None)
    return found[0] if found else 0


def bring_to_front(hwnd: int) -> None:
    """Windows often refuses SetForegroundWindow to a background program. Try the usual
    workarounds; the click on the box that follows activates the window anyway."""
    import ctypes

    import win32api
    import win32gui
    import win32process
    from pywinauto.keyboard import send_keys

    send_keys("%")  # an Alt press lets this program bring another window to the front
    try:
        win32gui.SetForegroundWindow(hwnd)
        return
    except Exception:
        pass
    user32 = ctypes.windll.user32
    here = win32api.GetCurrentThreadId()
    front = win32gui.GetForegroundWindow()
    there = win32process.GetWindowThreadProcessId(front)[0] if front else 0
    attached = bool(there and there != here and user32.AttachThreadInput(there, here, True))
    try:
        win32gui.BringWindowToTop(hwnd)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            log.info("Windows would not bring Claude to the front; clicking the box instead")
    finally:
        if attached:
            user32.AttachThreadInput(there, here, False)


def focused_prompt():
    """The focused UI Automation element, when it is a Claude message box."""
    from pywinauto.uia_defines import IUIA
    from pywinauto.uia_element_info import UIAElementInfo

    info = UIAElementInfo(IUIA().iuia.GetFocusedElement())
    if info.name == "Prompt" and info.control_type == "Edit":
        return info
    return None


def _rect(info) -> tuple[int, int, int, int]:
    r = info.rectangle
    return (r.left, r.top, r.right, r.bottom)


class ClaudeBox:
    """The message box you last clicked. Problems come back as short names: nowindow, noclick, empty."""

    def __init__(self, stopping: threading.Event) -> None:
        self.place = _saved_place()
        self.stopping = stopping
        self.jobs: queue.Queue = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()
        threading.Thread(target=self._watch_focus, daemon=True).start()

    def _watch_focus(self) -> None:
        """Remembers each Claude message box you click into."""
        import comtypes

        comtypes.CoInitialize()
        while not self.stopping.is_set():
            try:
                info = focused_prompt()
                if info is not None and _rect(info) != self.place:
                    self.place = _rect(info)
                    paths.BOX_PLACE.write_text(json.dumps(self.place))
            except Exception:
                pass
            time.sleep(0.4)

    def _run(self) -> None:
        import comtypes

        comtypes.CoInitialize()
        while True:
            fn, done, result = self.jobs.get()
            try:
                result["value"] = fn()
            except Exception as error:
                log.exception("box job failed")
                result["value"] = f"error: {error}"
            done.set()

    def _call(self, fn, seconds: float = 8.0):
        done, result = threading.Event(), {}
        self.jobs.put((fn, done, result))
        return result.get("value") if done.wait(seconds) else "timeout"

    # The four methods below run on the box thread.

    def _focus(self) -> str:
        import win32con
        import win32gui
        from pywinauto import mouse

        hwnd = claude_window()
        if not hwnd:
            return "nowindow"
        if not self.place:
            return "noclick"
        info = focused_prompt()
        if info is not None and win32gui.GetForegroundWindow() == hwnd and _rect(info) == self.place:
            return ""  # already in the right box
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        bring_to_front(hwnd)
        time.sleep(0.2)
        left, top, right, bottom = self.place
        mouse.click(coords=((left + right) // 2, (top + bottom) // 2))
        time.sleep(0.15)
        return ""

    def _text(self) -> str:
        from pywinauto.controls.uiawrapper import UIAWrapper

        info = focused_prompt()
        return UIAWrapper(info).window_text().strip() if info is not None else ""

    def _replace(self, text: str) -> None:
        import win32clipboard
        from pywinauto.keyboard import send_keys

        send_keys("^a")
        time.sleep(0.08)
        if text:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            send_keys("^v")
        else:
            send_keys("{BACKSPACE}")
        time.sleep(0.15)

    def _key(self, key: str, need_text: bool = False) -> str:
        from pywinauto.keyboard import send_keys

        problem = self._focus()
        if problem:
            return problem
        if need_text and not self._text():
            return "empty"
        send_keys(key)
        return ""

    # Called from the listening thread.

    def read(self) -> tuple[str, str]:
        """(problem, the text already in the box)."""

        def job():
            problem = self._focus()
            return (problem, "") if problem else ("", self._text())

        out = self._call(job)
        return out if isinstance(out, tuple) else (str(out), "")

    def write(self, text: str) -> str:
        def job():
            problem = self._focus()
            if not problem:
                self._replace(text)
            return problem

        return self._call(job) or ""

    def send(self) -> str:
        return self._call(lambda: self._key("{ENTER}", need_text=True)) or ""

    def escape(self) -> str:
        return self._call(lambda: self._key("{ESC}")) or ""


def clipboard_text() -> str | None:
    import win32clipboard

    try:
        win32clipboard.OpenClipboard()
        try:
            return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return None


def restore_clipboard(text: str | None) -> None:
    if text is None:
        return
    import win32clipboard

    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        win32clipboard.CloseClipboard()
    except Exception:
        pass
