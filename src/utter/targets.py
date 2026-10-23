"""Where the words go: the Claude desktop app's message box, or wherever your cursor is.

The Claude box: Windows UI Automation shows it as an Edit control named "Prompt" inside the
window titled "Claude". Utter remembers where you last clicked one, then clicks there and
pastes. Your words appear in it live, and Utter can read it back and change words in it.

The cursor: any other app (a terminal running Claude Code, an editor, a chat). Utter can't
read other apps, so the live words show on the strip only, and the final text is pasted once.

Every UI Automation call runs on one thread, because COM needs that.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import queue
import threading
import time

from . import settings as paths

log = logging.getLogger("utter")
DESKTOP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow"}


# --- windows ------------------------------------------------------------------------

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


def is_claude(hwnd: int) -> bool:
    import win32gui

    try:
        return win32gui.GetWindowText(hwnd) == "Claude" and win32gui.GetClassName(hwnd) == "Chrome_WidgetWin_1"
    except Exception:
        return False


def window_owner(hwnd: int) -> int:
    import win32process

    try:
        return win32process.GetWindowThreadProcessId(hwnd)[1]
    except Exception:
        return 0


def bring_to_front(hwnd: int) -> None:
    """Windows often refuses SetForegroundWindow to a background program. Try the usual
    workarounds; a click on the box afterwards activates the window anyway."""
    import win32api
    import win32con
    import win32gui
    from pywinauto.keyboard import send_keys

    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    if win32gui.GetForegroundWindow() == hwnd:
        return
    send_keys("%")  # an Alt press lets this program bring another window to the front
    try:
        win32gui.SetForegroundWindow(hwnd)
        return
    except Exception:
        pass
    user32 = ctypes.windll.user32
    here = win32api.GetCurrentThreadId()
    front = win32gui.GetForegroundWindow()
    there = window_owner_thread(front)
    attached = bool(there and there != here and user32.AttachThreadInput(there, here, True))
    try:
        win32gui.BringWindowToTop(hwnd)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            log.info("Windows would not bring the window to the front")
    finally:
        if attached:
            user32.AttachThreadInput(there, here, False)


def window_owner_thread(hwnd: int) -> int:
    import win32process

    try:
        return win32process.GetWindowThreadProcessId(hwnd)[0] if hwnd else 0
    except Exception:
        return 0


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


def open_clipboard(seconds: float = 1.0) -> bool:
    """Another app (a clipboard manager, a browser) often holds the clipboard for a moment."""
    import win32clipboard

    end = time.time() + seconds
    while True:
        try:
            win32clipboard.OpenClipboard()
            return True
        except Exception:
            if time.time() > end:
                return False
            time.sleep(0.05)


def paste(text: str) -> None:
    import win32clipboard
    from pywinauto.keyboard import send_keys

    if not open_clipboard():
        log.info("clipboard busy; typing the text instead")
        type_text(text)
        return
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()
    send_keys("^v")


def type_text(text: str) -> None:
    """Types `text` as Unicode key presses, for when the clipboard can't be used."""
    from pywinauto.keyboard import send_keys

    # Enter would send the message, so line breaks become spaces.
    escaped = "".join("{" + c + "}" if c in "+^%~(){}[]" else c for c in text.replace("\n", " "))
    send_keys(escaped, with_spaces=True, pause=0, vk_packet=True)


def clipboard_text() -> str | None:
    import win32clipboard

    try:
        if not open_clipboard():
            return None
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
        if not open_clipboard():
            return
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        pass


# --- the worker that does all the clicking and typing -------------------------------

class Hands:
    """One thread for every UI Automation and keyboard call, plus a watcher that remembers
    the Claude box you last clicked and the last window you used that isn't Utter's."""

    def __init__(self, stopping: threading.Event) -> None:
        self.box_place = _saved_place()
        self.last_window = 0
        self.stopping = stopping
        self.jobs: queue.Queue = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()
        threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self) -> None:
        import comtypes
        import win32gui

        comtypes.CoInitialize()
        me = os.getpid()
        while not self.stopping.is_set():
            try:
                front = win32gui.GetForegroundWindow()
                if front and window_owner(front) != me:
                    self.last_window = front
                info = focused_prompt()
                if info is not None and _rect(info) != self.box_place:
                    self.box_place = _rect(info)
                    paths.BOX_PLACE.write_text(json.dumps(self.box_place))
            except Exception:
                pass
            time.sleep(0.3)

    def _run(self) -> None:
        import comtypes

        comtypes.CoInitialize()
        while True:
            fn, done, result = self.jobs.get()
            try:
                result["value"] = fn()
            except Exception as error:
                log.exception("typing job failed")
                result["value"] = f"error: {error}"
            done.set()

    def call(self, fn, seconds: float = 8.0):
        done, result = threading.Event(), {}
        self.jobs.put((fn, done, result))
        return result.get("value") if done.wait(seconds) else "timeout"

    def pick(self, target: str):
        """The place to type into for this message."""
        import win32gui

        if target == "claude-app":
            return ClaudeBox(self)
        window = self.last_window
        if target == "cursor":
            return CursorTarget(self, window)
        if window and is_claude(window):
            return ClaudeBox(self)
        try:
            desktop = not window or win32gui.GetClassName(window) in DESKTOP_CLASSES
        except Exception:
            desktop = True
        if desktop and claude_window():
            return ClaudeBox(self)
        return CursorTarget(self, window)


def _saved_place():
    try:
        return tuple(json.loads(paths.BOX_PLACE.read_text()))
    except Exception:
        return None


# --- the two targets ----------------------------------------------------------------
# Every method returns a problem name ("" = fine): nowindow, noclick, empty, nowhere,
# notsupported, notfound, or "error: ..." / "timeout".

class ClaudeBox:
    name = "Claude app"
    live_typing = True  # the words appear in the box while you talk
    can_read = True

    def __init__(self, hands: Hands) -> None:
        self.hands = hands

    def _focus(self) -> str:
        from pywinauto import mouse

        import win32gui

        hwnd = claude_window()
        if not hwnd:
            return "nowindow"
        place = self.hands.box_place
        if not place:
            return "noclick"
        info = focused_prompt()
        if info is not None and win32gui.GetForegroundWindow() == hwnd and _rect(info) == place:
            return ""  # already in the right box
        bring_to_front(hwnd)
        time.sleep(0.2)
        left, top, right, bottom = place
        mouse.click(coords=((left + right) // 2, (top + bottom) // 2))
        time.sleep(0.15)
        return ""

    def _text(self) -> str:
        from pywinauto.controls.uiawrapper import UIAWrapper

        info = focused_prompt()
        return UIAWrapper(info).window_text().strip() if info is not None else ""

    def _replace(self, text: str) -> None:
        from pywinauto.keyboard import send_keys

        send_keys("^a")
        time.sleep(0.08)
        if text:
            paste(text)
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

    def read(self) -> tuple[str, str]:
        """(problem, the text in the box)."""

        def job():
            problem = self._focus()
            return (problem, "") if problem else ("", self._text())

        out = self.hands.call(job)
        return out if isinstance(out, tuple) else (str(out), "")

    def write(self, text: str) -> str:
        """Makes the box say `text`. New words at the end are added there, so the box doesn't
        flicker while you talk; any other change replaces the whole text."""
        from pywinauto.keyboard import send_keys

        def job():
            problem = self._focus()
            if problem:
                return problem
            current = self._text()
            if current == text.strip():
                return ""
            if current and text.startswith(current):
                send_keys("^{END}")
                paste(text[len(current):])
                time.sleep(0.1)
                if self._text() == text.strip():
                    return ""
            self._replace(text)
            return ""

        return self.hands.call(job) or ""

    def send(self) -> str:
        return self.hands.call(lambda: self._key("{ENTER}", need_text=True)) or ""

    def escape(self) -> str:
        return self.hands.call(lambda: self._key("{ESC}")) or ""


class CursorTarget:
    live_typing = False  # other apps can't be read, so the words are pasted once, at the end
    can_read = False

    def __init__(self, hands: Hands, window: int) -> None:
        import win32gui

        self.hands = hands
        self.window = window
        try:
            title = win32gui.GetWindowText(window) if window else ""
        except Exception:
            title = ""
        self.name = (title[:40] + "…") if len(title) > 40 else (title or "your cursor")
        self.typed = ""

    def _front(self) -> str:
        import win32gui

        if not self.window or not win32gui.IsWindow(self.window):
            return "nowhere"
        bring_to_front(self.window)
        time.sleep(0.15)
        return ""

    def read(self) -> tuple[str, str]:
        return ("nowhere", "") if not self.window else ("", "")

    def write(self, text: str) -> str:
        """Pastes `text` where the cursor is. An empty text does nothing."""
        if not text:
            return ""

        def job():
            problem = self._front()
            if not problem:
                paste(text)
                time.sleep(0.15)
                self.typed = text
            return problem

        return self.hands.call(job) or ""

    def _key(self, key: str) -> str:
        from pywinauto.keyboard import send_keys

        def job():
            problem = self._front()
            if not problem:
                send_keys(key)
            return problem

        return self.hands.call(job) or ""

    def send(self) -> str:
        return self._key("{ENTER}")

    def escape(self) -> str:
        return self._key("{ESC}")
