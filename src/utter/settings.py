"""Where Utter keeps its files, and the settings a person can change.

Everything lives in  %USERPROFILE%\\.utter : the settings file (config.toml, made by
`utter setup`), the Python environment, models, logs and small state files.

Not under AppData on purpose: the Microsoft Store's Python quietly redirects its writes to
AppData into a private folder, so other programs (and the installer) would not find them.
Set UTTER_HOME to use another folder, and UTTER_MODELS for the models (handy for tests).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

DATA = Path(os.environ.get("UTTER_HOME") or Path.home() / ".utter")
CONFIG_FILE = DATA / "config.toml"
MODELS = Path(os.environ.get("UTTER_MODELS") or DATA / "models")
VOSK_MODEL = MODELS / "vosk-model-small-en-us-0.15"
WHISPER_MODELS = MODELS / "whisper"
STATE = DATA / "state"
CLIPS = STATE / "clips"
LOG = DATA / "utter.log"
VOICE_OFF = DATA / "voice-off"  # exists = don't read answers aloud
LISTENING_FLAG = STATE / "listening.flag"  # exists = the mic is open, so stay silent
PLAYER_PID = STATE / "player.pid"
SPEAKING = STATE / "speaking.txt"  # what the answer playing now says
LAST_ANSWER = STATE / "last-answer.txt"  # for "repeat that"
BOX_PLACE = STATE / "box.json"
STRIP_PLACE = STATE / "strip.json"


@dataclass
class Settings:
    # --- Waking and sending ---

    # Say one of these to wake Utter. The wake-word engine only knows common English
    # words, so "Claude" also comes through as "cloud" or "clawed".
    wake_phrases: list[str] = field(
        default_factory=lambda: ["hey claude", "hey cloud", "hey clawed", "okay claude", "hi claude"]
    )
    # A keyboard shortcut that does the same as the wake phrase. Press it again while
    # listening to send. Empty = no shortcut. Examples: "ctrl+alt+h", "ctrl+shift+f9".
    hotkey: str = "ctrl+alt+h"
    # How a message is sent:
    #   "phrase" = only when you end with a send phrase ("...send it"). Pauses never send.
    #   "pause"  = also when you stop talking for pause_seconds.
    send_mode: str = "phrase"
    # End what you say with one of these to send it.
    send_phrases: list[str] = field(
        default_factory=lambda: ["send it", "send that", "send it now", "that's it", "thats it", "over and out"]
    )
    # In "pause" send mode, this much quiet sends the message.
    pause_seconds: float = 2.0
    # When Utter isn't sure it heard you right, it types the words but doesn't send them,
    # and reads them back so you can check.
    check_unclear: bool = True

    # --- Where the words go ---

    # "auto"       = the Claude app's message box when the Claude app is in front,
    #                otherwise wherever your cursor is (a terminal, an editor, any app).
    # "claude-app" = always the Claude app's message box.
    # "cursor"     = always wherever your cursor is.
    target: str = "auto"

    # --- Hearing you right ---

    # Words Utter should expect: names, product words, jargon.
    words: list[str] = field(default_factory=list)
    # Fix words it keeps getting wrong: "what it hears" = "what to type".
    replacements: dict[str, str] = field(default_factory=dict)
    # Take out "um", "uh" and "erm".
    remove_fillers: bool = True
    # The language you speak, as a two-letter code ("en", "de", "es", "fr", "hi", "bn", ...).
    # Anything but "en" switches to the multilingual speech models (run install.ps1 again
    # to download them). The wake phrase and commands stay English.
    language: str = "en"
    # Speech models: a fast one for the live words, a better one for the final text.
    # "base.en" is faster on slow computers; "medium.en" is more accurate.
    live_model: str = "base.en"
    final_model: str = "small.en"
    # Sound louder than this counts as talking. Raise it in a noisy room.
    speaking_level: float = 0.008
    # Microphone name (or part of it). Empty = the Windows default microphone.
    microphone: str = ""

    # --- Timing ---

    # Stop listening after this much quiet, and leave your words in the box unsent.
    quiet_seconds: float = 15.0
    # Go back to waiting, with a soft tone, if you say nothing this long after you wake Utter.
    nothing_heard_seconds: float = 5.0
    # A short command ("scratch that") is acted on after this much quiet.
    command_pause_seconds: float = 1.5
    # Longest single message, in seconds.
    max_message_seconds: float = 120.0

    # --- Speaking ---

    # Read Claude's answers aloud (also toggled by "voice off" / "voice on").
    speak_replies: bool = True
    # "edge"    = natural Microsoft Edge voices (online; the text is sent to Microsoft).
    # "windows" = the voices built into Windows (offline, more robotic).
    voice_engine: str = "edge"
    # Edge voice. List them with:  python -m edge_tts --list-voices
    voice: str = "en-US-AndrewMultilingualNeural"
    # Windows voice name (or part of it), for voice_engine = "windows". Empty = the default.
    windows_voice: str = ""
    # Speaking speed in percent: 0 = normal, -30 = slower, 25 = faster.
    speaking_rate: int = 0
    # Longest answer read aloud, in characters. Longer answers are cut at a sentence.
    max_spoken_chars: int = 900
    # Short beeps when Utter starts and stops listening, instead of saying "Yes?".
    cue_sounds: bool = True

    # --- The status strip ---

    # "normal" or "large".
    strip_size: str = "normal"
    # Black and yellow, for easier reading.
    high_contrast: bool = False

    @property
    def wake_name(self) -> str:
        return self.wake_phrases[0].title() if self.wake_phrases else "Hey Claude"

    def model(self, which: str) -> str:
        """The live or final speech model, multilingual when the language isn't English."""
        name = self.live_model if which == "live" else self.final_model
        return name.removesuffix(".en") if self.language != "en" else name


def load(path: Path = CONFIG_FILE) -> Settings:
    """The settings file's values over the defaults. A missing or broken file gives the defaults."""
    settings = Settings()
    try:
        values = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return settings
    known = {f.name for f in fields(Settings)}
    for name, value in values.items():
        if name not in known:
            continue
        current = getattr(settings, name)
        if isinstance(current, bool) != isinstance(value, bool):
            continue
        if isinstance(value, type(current)):
            setattr(settings, name, value)
        elif isinstance(value, int) and isinstance(current, float):
            setattr(settings, name, float(value))
    settings.wake_phrases = [p.lower().strip() for p in settings.wake_phrases if str(p).strip()]
    settings.send_phrases = [p.lower().strip() for p in settings.send_phrases if str(p).strip()]
    settings.words = [str(w).strip() for w in settings.words if str(w).strip()]
    settings.replacements = {str(k).lower(): str(v) for k, v in settings.replacements.items()}
    return settings


def default_file_text() -> str:
    """config.toml as `utter setup` first writes it: every setting, with its comment."""
    import inspect
    import re

    source = inspect.getsource(Settings)
    out = ["# Utter settings. After a change, choose Restart in the tray icon's menu.", ""]
    comments: list[str] = []
    defaults = Settings()
    names = {f.name for f in fields(Settings)}
    for line in source.splitlines():
        s = line.strip()
        if s.startswith("# ---"):
            out.extend([s.replace("# ---", "# ===").replace("---", "==="), ""])
            continue
        if s.startswith("#"):
            comments.append(s)
            continue
        m = re.match(r"(\w+):", s)
        if m and m.group(1) in names:
            name = m.group(1)
            out.extend(comments)
            if name == "words":
                out.append('# Example: words = ["Kubernetes", "PostgreSQL", "Priya"]')
            if name == "replacements":
                out.append('# Example: replacements = { "post gress" = "Postgres", "get hub" = "GitHub" }')
            out.append(f"{name} = {_toml(getattr(defaults, name))}")
            out.append("")
        comments = []
    return "\n".join(out)


def missing_settings_text(existing: str) -> str:
    """The settings an older config.toml doesn't have yet, each with its comment, ready to append."""
    import re

    present = set(re.findall(r"(?m)^\s*(\w+)\s*=", existing))
    blocks = []
    for block in default_file_text().split("\n\n"):
        lines = [line for line in block.splitlines() if line.strip()]
        setting = next((line for line in reversed(lines) if not line.startswith("#")), "")
        name = setting.split("=")[0].strip()
        if name and name not in present:
            blocks.append("\n".join(line for line in lines if not line.startswith("# ===")))
    if not blocks:
        return ""
    return "# --- Added by a newer version of Utter ---\n\n" + "\n\n".join(blocks) + "\n"


def _toml(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_toml(k)} = {_toml(v)}" for k, v in value.items()) + " }" if value else "{}"
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'
