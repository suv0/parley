"""The small status strip that stays on top of other windows, and the tray icon."""

from __future__ import annotations

import json
import os
import queue
import subprocess

from . import settings as paths
from .app import paused, stopping, ui_events
from .voice import stop_answer

COLORS = {"idle": "#22a06b", "listening": "#e5484d", "working": "#f5a524", "paused": "#8b8b8b", "problem": "#f5a524"}
BG, FG, DIM = "#1f1f1f", "#f2f2f2", "#a0a0a0"


def help_lines(s: paths.Settings) -> list[tuple[str, str]]:
    wake = s.wake_name
    send = s.send_phrases[0] if s.send_phrases else "send it"
    return [
        (wake, "then talk"),
        (f"…{send}", "send your message"),
        (f"{wake}, send it", "send what's in the box"),
        (f"{wake}, scratch that", "clear the box"),
        (f"{wake}, quiet", "stop reading an answer"),
        (f"{wake}, stop", "stop Claude (presses Esc)"),
        (f"{wake}, voice off / on", "spoken answers"),
        (f"{wake}, help", "show or hide this"),
        ("", "Click a Claude message box once so I know where to type. Pauses never send."),
    ]


def strip(s: paths.Settings) -> None:
    """Runs the strip on this thread until Quit."""
    import tkinter as tk

    idle_text = f"Say “{s.wake_name}”"
    root = tk.Tk()
    root.title("Parley")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.93)
    root.configure(bg=BG)

    top = tk.Frame(root, bg=BG)
    top.pack(fill="x", padx=10, pady=6)
    dot = tk.Canvas(top, width=12, height=12, bg=BG, highlightthickness=0)
    dot_id = dot.create_oval(1, 1, 11, 11, fill=COLORS["working"], outline="")
    dot.pack(side="left", padx=(0, 8))
    label = tk.Label(top, text="Starting up", bg=BG, fg=FG, font=("Segoe UI", 10), anchor="w")
    label.pack(side="left", fill="x", expand=True)
    help_btn = tk.Label(top, text=" ? ", bg="#333333", fg=FG, font=("Segoe UI", 9, "bold"), cursor="hand2")
    help_btn.pack(side="right", padx=(8, 0))

    live = tk.Label(root, text="", bg=BG, fg=DIM, font=("Segoe UI", 9), anchor="w", justify="left", wraplength=320)
    help_box = tk.Frame(root, bg=BG)
    for left, right in help_lines(s):
        row = tk.Frame(help_box, bg=BG)
        row.pack(fill="x")
        if left:
            tk.Label(row, text=left, bg=BG, fg=FG, font=("Segoe UI", 9, "bold"), anchor="w", width=24).pack(side="left")
            tk.Label(row, text=right, bg=BG, fg=DIM, font=("Segoe UI", 9), anchor="w").pack(side="left")
        else:
            tk.Label(row, text=right, bg=BG, fg=DIM, font=("Segoe UI", 8, "italic"), anchor="w",
                     wraplength=320, justify="left").pack(side="left", pady=(4, 0))
    showing_help = {"on": False}

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
            help_box.pack(fill="x", padx=10, pady=(0, 8))
        else:
            help_box.pack_forget()

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
            live.config(text=("…" + words[-160:]) if len(words) > 160 else words)
            live.pack(fill="x", padx=10, pady=(0, 6), before=help_box if showing_help["on"] else None)
        else:
            live.pack_forget()

    def poll() -> None:
        try:
            while True:
                kind, text = ui_events.get_nowait()
                if kind == "status":
                    state, msg, words = (text.split("\t") + ["", ""])[:3]
                    set_state(state, msg, words)
                    if idle_timer["id"]:
                        root.after_cancel(idle_timer["id"])
                        idle_timer["id"] = None
                elif kind == "idle-later":
                    idle_timer["id"] = root.after(4000, lambda: set_state("idle", idle_text, ""))
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
            ui_events.put(("status", f"idle\tSay “{s.wake_name}”\t"))
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

    item = pystray.MenuItem
    icon = pystray.Icon(
        "parley",
        image(COLORS["idle"]),
        "Parley (voice for Claude)",
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
            pystray.Menu.SEPARATOR,
            item("Quit", quit_app),
        ),
    )
    icon.run_detached()
