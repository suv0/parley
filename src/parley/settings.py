"""Where Parley keeps its files, and the settings a person can change.

Everything lives in  %USERPROFILE%\\.parley : the settings file (config.toml, made by
`parley setup`), the Python environment, models, logs and small state files.

Not under AppData on purpose: the Microsoft Store's Python quietly redirects its writes to
AppData into a private folder, so other programs (and the installer) would not find them.
Set PARLEY_HOME to use another folder (handy for tests).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

DATA = Path(os.environ.get("PARLEY_HOME") or Path.home() / ".parley")
CONFIG_FILE = DATA / "config.toml"
MODELS = DATA / "models"
VOSK_MODEL = MODELS / "vosk-model-small-en-us-0.15"
WHISPER_MODELS = MODELS / "whisper"
STATE = DATA / "state"
CLIPS = STATE / "clips"
LOG = DATA / "parley.log"
VOICE_OFF = DATA / "voice-off"  # exists = don't read answers aloud
LISTENING_FLAG = STATE / "listening.flag"  # exists = the mic is open, so stay silent
PLAYER_PID = STATE / "player.pid"
BOX_PLACE = STATE / "box.json"
STRIP_PLACE = STATE / "strip.json"


@dataclass
class Settings:
    # Say one of these to wake Parley. The wake-word engine only knows common English
    # words, so "Claude" also comes through as "cloud" or "clawed".
    wake_phrases: list[str] = field(
        default_factory=lambda: ["hey claude", "hey cloud", "hey clawed", "okay claude", "hi claude"]
    )
    # End what you say with one of these to send it. Pauses never send.
    send_phrases: list[str] = field(
        default_factory=lambda: ["send it", "send that", "send it now", "that's it", "thats it", "over and out"]
    )
    # Any Microsoft Edge voice. List them with:  python -m edge_tts --list-voices
    voice: str = "en-US-AndrewMultilingualNeural"
    # Read Claude's answers aloud (also toggled by "voice off" / "voice on").
    speak_replies: bool = True
    # Longest answer read aloud, in characters. Longer answers are cut at a sentence.
    max_spoken_chars: int = 900
    # Stop listening after this much quiet, and leave your words in the box unsent.
    quiet_seconds: float = 15.0
    # Give up if you say nothing this long after "Yes?".
    nothing_heard_seconds: float = 8.0
    # A short command ("scratch that") is acted on after this much quiet.
    command_pause_seconds: float = 1.5
    # Longest single message, in seconds.
    max_message_seconds: float = 120.0
    # Sound louder than this counts as talking. Raise it in a noisy room.
    speaking_level: float = 0.008
    # Whisper models: a fast one for the live words, a better one for the final text.
    live_model: str = "base.en"
    final_model: str = "small.en"
    # Microphone name (or part of it). Empty = the Windows default microphone.
    microphone: str = ""

    @property
    def wake_name(self) -> str:
        return self.wake_phrases[0].title() if self.wake_phrases else "Hey Claude"


def load(path: Path = CONFIG_FILE) -> Settings:
    """The settings file's values over the defaults. A missing or broken file gives the defaults."""
    settings = Settings()
    try:
        values = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return settings
    known = {f.name: f for f in fields(Settings)}
    for name, value in values.items():
        if name in known and isinstance(value, type(getattr(settings, name))):
            setattr(settings, name, value)
        elif name in known and isinstance(value, int) and isinstance(getattr(settings, name), float):
            setattr(settings, name, float(value))
    settings.wake_phrases = [p.lower().strip() for p in settings.wake_phrases if p.strip()]
    settings.send_phrases = [p.lower().strip() for p in settings.send_phrases if p.strip()]
    return settings


def default_file_text() -> str:
    """config.toml as `parley setup` first writes it: every setting, with its comment."""
    import inspect
    import re

    source = inspect.getsource(Settings)
    out = ["# Parley settings. Quit Parley from the tray icon and start it again after a change.", ""]
    comments: list[str] = []
    defaults = Settings()
    for line in source.splitlines():
        s = line.strip()
        if s.startswith("#"):
            comments.append(s)
            continue
        m = re.match(r"(\w+):", s)
        if m and m.group(1) in {f.name for f in fields(Settings)}:
            out.extend(comments)
            out.append(f"{m.group(1)} = {_toml(getattr(defaults, m.group(1)))}")
            out.append("")
        comments = []
    return "\n".join(out)


def _toml(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'
