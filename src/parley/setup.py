"""Install and uninstall steps: models, the Claude Code hook, shortcuts, and a microphone check."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from . import settings as paths

VOSK_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
HOOK_MARK = "parley.speak_reply"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
PROGRAMS = Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming") / "Microsoft/Windows/Start Menu/Programs"
SHORTCUTS = [PROGRAMS / "Startup" / "Parley.lnk", PROGRAMS / "Parley.lnk"]


def step(text: str) -> None:
    print(f"\n== {text}", flush=True)


def python_exe(windowless: bool = False) -> Path:
    """This environment's python.exe, or pythonw.exe (no console window)."""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if windowless and w.exists() else exe.with_name("python.exe")


# --- settings file ------------------------------------------------------------------

def write_config() -> None:
    if paths.CONFIG_FILE.exists():
        text = paths.CONFIG_FILE.read_text(encoding="utf-8")
        added = paths.missing_settings_text(text)
        if added:
            paths.CONFIG_FILE.write_text(text.rstrip() + "\n\n" + added, encoding="utf-8")
            print(f"Keeping your settings, and adding the new ones (with their defaults): {paths.CONFIG_FILE}")
        else:
            print(f"Keeping your settings: {paths.CONFIG_FILE}")
        return
    paths.DATA.mkdir(parents=True, exist_ok=True)
    paths.CONFIG_FILE.write_text(paths.default_file_text(), encoding="utf-8")
    print(f"Settings: {paths.CONFIG_FILE}")


# --- models -------------------------------------------------------------------------

def download_models(settings: paths.Settings) -> None:
    paths.MODELS.mkdir(parents=True, exist_ok=True)
    if paths.VOSK_MODEL.exists():
        print("Wake-word model: already here")
    else:
        zip_path = paths.MODELS / "vosk.zip"
        print("Wake-word model (about 40 MB)...", flush=True)

        shown = {"tens": -1}

        def progress(blocks, size, total):
            percent = min(100, blocks * size * 100 // total) if total > 0 else 0
            if percent // 10 != shown["tens"]:
                shown["tens"] = percent // 10
                print(f"  {percent}%", flush=True)

        urllib.request.urlretrieve(VOSK_URL, zip_path, progress)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(paths.MODELS)
        zip_path.unlink()

    from faster_whisper import download_model

    sizes = {"tiny": "75 MB", "base": "140 MB", "small": "460 MB", "medium": "1.5 GB"}
    for name in dict.fromkeys([settings.model("live"), settings.model("final")]):
        print(f"Speech model {name} (about {sizes.get(name.removesuffix('.en'), 'a few hundred MB')}, once)...", flush=True)
        download_model(name, cache_dir=str(paths.WHISPER_MODELS))
    print("Models ready.")


# --- the Claude Code hook that reads answers aloud ----------------------------------

def hook_command() -> str:
    return f'"{python_exe()}" -m {HOOK_MARK}'


def with_hook(claude_settings: dict, command: str) -> dict:
    """Claude's settings with Parley's Stop hook added once. Every other hook stays as it was."""
    out = without_hook(claude_settings)
    stop = out.setdefault("hooks", {}).setdefault("Stop", [])
    stop.append({"hooks": [{"type": "command", "command": command, "timeout": 60, "async": True}]})
    return out


def without_hook(claude_settings: dict) -> dict:
    """Claude's settings with Parley's Stop hook taken out (and any group it leaves empty)."""
    out = json.loads(json.dumps(claude_settings))
    hooks = out.get("hooks")
    if not isinstance(hooks, dict) or not isinstance(hooks.get("Stop"), list):
        return out
    groups = []
    for group in hooks["Stop"]:
        inner = [h for h in group.get("hooks", []) if HOOK_MARK not in str(h.get("command", ""))]
        if inner:
            groups.append({**group, "hooks": inner})
        elif not group.get("hooks"):
            groups.append(group)
    if groups:
        hooks["Stop"] = groups
    else:
        del hooks["Stop"]
    if not hooks:
        del out["hooks"]
    return out


def change_claude_settings(change) -> None:
    current = {}
    if CLAUDE_SETTINGS.exists():
        text = CLAUDE_SETTINGS.read_text(encoding="utf-8")
        current = json.loads(text) if text.strip() else {}
        shutil.copyfile(CLAUDE_SETTINGS, CLAUDE_SETTINGS.with_name("settings.json.parley-backup"))
    new = change(current)
    if new == current:
        return
    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    CLAUDE_SETTINGS.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def add_hook() -> None:
    change_claude_settings(lambda s: with_hook(s, hook_command()))
    print(f"Claude Code will read answers aloud (hook added to {CLAUDE_SETTINGS}).")


def remove_hook() -> None:
    if CLAUDE_SETTINGS.exists():
        change_claude_settings(without_hook)
        print("Removed the read-aloud hook from Claude Code.")


# --- shortcuts and the running app --------------------------------------------------

def powershell(script: str) -> None:
    """Shortcuts live under AppData, which the Store's Python would redirect, so PowerShell writes them."""
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], check=True)


def ps_quote(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def add_shortcuts() -> None:
    script = "$s=New-Object -ComObject WScript.Shell;"
    for path in SHORTCUTS:
        script += (
            f"New-Item -ItemType Directory -Force {ps_quote(path.parent)} | Out-Null;"
            f"$l=$s.CreateShortcut({ps_quote(path)});"
            f"$l.TargetPath={ps_quote(python_exe(windowless=True))};$l.Arguments='-m parley';"
            f"$l.WorkingDirectory={ps_quote(paths.DATA)};$l.Description='Parley: hands-free voice for Claude';"
            "$l.Save();"
        )
    powershell(script)
    print("Parley starts when Windows starts, and is in the Start menu.")


def remove_shortcuts() -> None:
    powershell(";".join(f"Remove-Item -LiteralPath {ps_quote(p)} -ErrorAction SilentlyContinue" for p in SHORTCUTS))


def shortcut_exists() -> bool:
    out = subprocess.run(["powershell", "-NoProfile", "-Command", f"Test-Path -LiteralPath {ps_quote(SHORTCUTS[0])}"],
                         capture_output=True, text=True)
    return out.stdout.strip() == "True"


def start_app() -> None:
    subprocess.Popen([str(python_exe(windowless=True)), "-m", "parley"], cwd=paths.DATA,
                     creationflags=subprocess.DETACHED_PROCESS)
    print("Parley is running. Look for the small strip at the bottom right of your screen.")


def stop_app() -> None:
    pid_file = paths.STATE / "app.pid"
    try:
        pid = pid_file.read_text().strip()
    except OSError:
        return
    if pid.isdigit():
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
    pid_file.unlink(missing_ok=True)


# --- checks -------------------------------------------------------------------------

def mic_works(settings: paths.Settings) -> bool:
    import sounddevice as sd

    try:
        with sd.InputStream(samplerate=16000, channels=1, dtype="int16", device=settings.microphone or None):
            pass
        return True
    except Exception as error:
        print(f"Microphone problem: {error}")
        return False


MIC_HELP = """\
Windows is blocking the microphone. Open  Settings > Privacy & security > Microphone  and turn on:
  - Microphone access
  - Let apps access your microphone
  - Let desktop apps access your microphone   (and Python, if it is listed)
Then run:  install.ps1  again, or start Parley from the Start menu."""


def install(start: bool = True) -> int:
    paths.STATE.mkdir(parents=True, exist_ok=True)
    step("Settings")
    write_config()
    settings = paths.load()
    step("Models")
    download_models(settings)
    step("Claude Code")
    add_hook()
    step("Shortcuts")
    add_shortcuts()
    step("Microphone")
    ok = mic_works(settings)
    if ok:
        print("The microphone works.")
    else:
        print(MIC_HELP)
        subprocess.run(["explorer", "ms-settings:privacy-microphone"])
    stop_app()
    if start:
        step("Starting")
        start_app()
    return 0 if ok else 2


def uninstall() -> int:
    stop_app()
    remove_hook()
    remove_shortcuts()
    print("Parley is stopped and removed from Claude Code and the Start menu.")
    return 0


def doctor() -> int:
    settings = paths.load()
    checks = [
        ("Settings file", paths.CONFIG_FILE.exists()),
        ("Wake-word model", paths.VOSK_MODEL.exists()),
        *[(f"Speech model {m}", any(paths.WHISPER_MODELS.glob(f"models--*faster-whisper-{m}")))
          for m in dict.fromkeys([settings.model("live"), settings.model("final")])],
        ("Read-aloud hook in Claude Code", CLAUDE_SETTINGS.exists() and HOOK_MARK in CLAUDE_SETTINGS.read_text("utf-8")),
        ("Starts with Windows", shortcut_exists()),
        ("Microphone", mic_works(settings)),
    ]
    for name, ok in checks:
        print(f"  [{'ok' if ok else '!!'}] {name}")
    print(f"\nLog: {paths.LOG}")
    return 0 if all(ok for _, ok in checks) else 1
