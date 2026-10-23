"""The small status strip that stays on top of other windows, and the tray icon."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys

from . import settings as paths
from .app import paused, stopping, ui_events
from .voice import stop_answer

COLORS = {"idle": "#22a06b", "listening": "#e5484d", "working": "#f5a524", "paused": "#8b8b8b", "problem": "#f5a524"}
THEMES = {
    # background, text, quiet text, button
    "normal": ("#1f1f1f", "#f2f2f2", "#a0a0a0", "#333333"),
    "contrast": ("#000000", "#ffffff", "#ffd400", "#333333"),
}


def help_lines(s: paths.Settings) -> list[tuple[str, str]]:
    wake = s.wake_name
    send = s.send_phrases[0] if s.send_phrases else "send it"
    start = f"{wake}  (or {s.hotkey})" if s.hotkey else wake
    return [
        (start, "then talk"),
        (f"…{send}", "send your message" + (f" (or {s.hotkey} again)" if s.hotkey else "")),
        (f"{wake}, send it", "send what's typed"),
        (f"{wake}, scratch that", "clear the box"),
        (f"{wake}, read it back", "hear your message"),
        (f"{wake}, change X to Y", "fix a word"),
        (f"{wake}, spell A B C", "type letters"),
        (f"{wake}, type stop", "type a command word"),
        (f"{wake}, cancel", "stop listening, type nothing"),
        (f"{wake}, repeat that", "hear the answer again"),
        (f"{wake}, more", "the rest of the answer"),
        (f"{wake}, skip / go back / pause", "move around the answer"),
        (f"{wake}, slower / faster", "reading speed"),
        (f"{wake}, quiet", "stop reading the answer"),
        (f"{wake}, stop", "stop Claude (presses Esc)"),
        (f"{wake}, what's happening", "hear what Utter is doing"),
        (f"{wake}, go to sleep", f"only “{wake}, wake up” wakes it"),
        (f"{wake}, voice off / on", "spoken answers"),
        (f"{wake}, help", "show this and hear the commands"),
        ("", "In the Claude app, click its message box once. Anywhere else, words go where your cursor is."
             + (" Pauses never send." if s.send_mode == "phrase" else "")),
    ]


def strip(s: paths.Settings) -> None:
    """Runs the strip on this thread until Quit."""
    import tkinter as tk

    bg, fg, dim, button = THEMES["contrast" if s.high_contrast else "normal"]
    scale = 1.5 if s.strip_size == "large" else 1.0
    size = lambda n: round(n * scale)  # noqa: E731
    wrap = size(340)
    idle_text = {"text": f"Say “{s.wake_name}”"}

    root = tk.Tk()
    root.title("Utter")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 1.0 if s.high_contrast else 0.93)
    root.configure(bg=bg, highlightthickness=2 if s.high_contrast else 0, highlightbackground="#ffd400")

    top = tk.Frame(root, bg=bg)
    top.pack(fill="x", padx=size(10), pady=size(6))
    dot_px = size(12)
    dot = tk.Canvas(top, width=dot_px, height=dot_px, bg=bg, highlightthickness=0)
    dot_id = dot.create_oval(1, 1, dot_px - 1, dot_px - 1, fill=COLORS["working"], outline="")
    dot.pack(side="left", padx=(0, size(8)))
    label = tk.Label(top, text="Starting up", bg=bg, fg=fg, font=("Segoe UI", size(10)), anchor="w",
                     justify="left", wraplength=wrap)
    label.pack(side="left", fill="x", expand=True)
    help_btn = tk.Label(top, text=" ? ", bg=button, fg=fg, font=("Segoe UI", size(9), "bold"), cursor="hand2")
    help_btn.pack(side="right", padx=(size(8), 0))

    live = tk.Label(root, text="", bg=bg, fg=dim, font=("Segoe UI", size(9)), anchor="w", justify="left",
                    wraplength=wrap)
    help_box = tk.Frame(root, bg=bg)
    for left, right in help_lines(s):
        row = tk.Frame(help_box, bg=bg)
        row.pack(fill="x")
        if left:
            tk.Label(row, text=left, bg=bg, fg=fg, font=("Segoe UI", size(9), "bold"), anchor="w",
                     width=30).pack(side="left")
            tk.Label(row, text=right, bg=bg, fg=dim, font=("Segoe UI", size(9)), anchor="w").pack(side="left")
        else:
            tk.Label(row, text=right, bg=bg, fg=dim, font=("Segoe UI", size(8), "italic"), anchor="w",
                     wraplength=size(420), justify="left").pack(side="left", pady=(size(4), 0))
    showing_help = {"on": False}

    def keep_on_screen() -> None:
        root.update_idletasks()
        x, y = root.winfo_x(), root.winfo_y()
        right = root.winfo_vrootwidth() if root.winfo_vrootwidth() > 1 else root.winfo_screenwidth()
        bottom = root.winfo_screenheight()
        x = min(x, right - root.winfo_reqwidth() - 8)
        y = min(y, bottom - root.winfo_reqheight() - 48)
        root.geometry(f"+{max(0, x)}+{max(0, y)}")

    def place() -> None:
        root.update_idletasks()
        try:
            x, y = json.loads(paths.STRIP_PLACE.read_text())
            if not (-50 < x < root.winfo_vrootwidth() and -50 < y < root.winfo_vrootheight()):
                raise ValueError("off screen")
        except Exception:
            x = root.winfo_screenwidth() - root.winfo_reqwidth() - 24
            y = root.winfo_screenheight() - root.winfo_reqheight() - 72
        root.geometry(f"+{x}+{y}")

    def toggle_help(_event=None) -> None:
        showing_help["on"] = not showing_help["on"]
        if showing_help["on"]:
            help_box.pack(fill="x", padx=size(10), pady=(0, size(8)))
        else:
            help_box.pack_forget()
        keep_on_screen()

    help_btn.bind("<Button-1>", toggle_help)

    drag = {"x": 0, "y": 0}

    def start_drag(event) -> None:
        drag["x"], drag["y"] = event.x_root - root.winfo_x(), event.y_root - root.winfo_y()

    def do_drag(event) -> None:
        root.geometry(f"+{event.x_root - drag['x']}+{event.y_root - drag['y']}")

    def end_drag(_event) -> None:
        try:
            paths.STRIP_PLACE.write_text(json.dumps([root.winfo_x(), root.winfo_y()]))
        except OSError:
            pass

    for widget in (root, top, label, dot):
        widget.bind("<ButtonPress-1>", start_drag)
        widget.bind("<B1-Motion>", do_drag)
        widget.bind("<ButtonRelease-1>", end_drag)

    idle_timer = {"id": None}

    def set_state(state: str, text: str, words: str) -> None:
        if paused.is_set() and state == "idle":
            state, text = "paused", "Paused. Resume from the tray icon"
        dot.itemconfig(dot_id, fill=COLORS.get(state, COLORS["working"]))
        label.config(text=text)
        if words:
            live.config(text=("…" + words[-200:]) if len(words) > 200 else words)
            live.pack(fill="x", padx=size(10), pady=(0, size(6)), before=help_box if showing_help["on"] else None)
        else:
            live.pack_forget()
        keep_on_screen()

    def poll() -> None:
        try:
            while True:
                kind, text = ui_events.get_nowait()
                if kind == "status":
                    state, msg, words = (text.split("\t") + ["", ""])[:3]
                    if state == "idle" and msg.startswith("Say “"):
                        idle_text["text"] = msg
                    set_state(state, msg, words)
                    if idle_timer["id"]:
                        root.after_cancel(idle_timer["id"])
                        idle_timer["id"] = None
                elif kind == "idle-later":
                    if text:
                        idle_text["text"] = text
                    idle_timer["id"] = root.after(5000, lambda: set_state("idle", idle_text["text"], ""))
                elif kind == "help":
                    toggle_help()
                elif kind == "visible":
                    root.deiconify() if text == "show" else root.withdraw()
                elif kind == "quit":
                    root.destroy()
                    return
        except queue.Empty:
            pass
        root.after(150, poll)

    place()
    root.after(150, poll)
    root.mainloop()


def restart() -> None:
    """Starts a new Utter that waits for this one to quit (so a settings change takes effect)."""
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    subprocess.Popen([exe if os.path.exists(exe) else sys.executable, "-m", "utter", "run", "--after",
                      str(os.getpid())], cwd=paths.DATA)


def tray(s: paths.Settings) -> None:
    """Starts the tray icon on its own thread."""
    import pystray
    from PIL import Image, ImageDraw

    def image(color: str):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse((8, 8, 56, 56), fill=color)
        return img

    visible = {"on": True}

    def toggle_pause(icon, _item):
        if paused.is_set():
            paused.clear()
            icon.icon = image(COLORS["idle"])
            ui_events.put(("idle-later", ""))
            ui_events.put(("status", "idle\tListening again\t"))
        else:
            paused.set()
            icon.icon = image(COLORS["paused"])
            ui_events.put(("status", "paused\tPaused. Resume from the tray icon\t"))

    def toggle_strip(_icon, _item):
        visible["on"] = not visible["on"]
        ui_events.put(("visible", "show" if visible["on"] else "hide"))

    def toggle_voice(_icon, _item):
        paths.VOICE_OFF.unlink(missing_ok=True) if paths.VOICE_OFF.exists() else paths.VOICE_OFF.touch()

    def open_path(path) -> None:
        if path.exists():
            os.startfile(path)

    def quit_app(icon, _item):
        stopping.set()
        ui_events.put(("quit", ""))
        icon.stop()

    def restart_app(icon, item):
        restart()
        quit_app(icon, item)

    item = pystray.MenuItem
    icon = pystray.Icon(
        "utter",
        image(COLORS["idle"]),
        "Utter (voice for Claude)",
        menu=pystray.Menu(
            item(lambda _: "Resume listening" if paused.is_set() else "Pause listening", toggle_pause, default=True),
            item("Stop reading the answer", lambda i, _: stop_answer()),
            item(lambda _: "Turn spoken answers on" if paths.VOICE_OFF.exists() else "Turn spoken answers off",
                 toggle_voice),
            item(lambda _: "Hide the status strip" if visible["on"] else "Show the status strip", toggle_strip),
            pystray.Menu.SEPARATOR,
            item("Help: what can I say?", lambda i, _: ui_events.put(("help", "toggle"))),
            item("Microphone settings…",
                 lambda i, _: subprocess.run(["explorer", "ms-settings:privacy-microphone"])),
            item("Open the settings file", lambda i, _: open_path(paths.CONFIG_FILE)),
            item("Open the log", lambda i, _: open_path(paths.LOG)),
            item("Restart (after changing settings)", restart_app),
            pystray.Menu.SEPARATOR,
            item("Quit", quit_app),
        ),
    )
    icon.run_detached()
