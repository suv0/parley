"""Speaking: short spoken replies ("Yes?", "Sent.") and stopping an answer mid-sentence."""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
from pathlib import Path

from . import settings as paths

NO_WINDOW = 0x08000000


def make_mp3(text: str, voice: str, out: Path) -> None:
    import edge_tts

    out.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(edge_tts.Communicate(text, voice).save(str(out)))


def clip(text: str, voice: str) -> Path:
    """A cached mp3 of `text`. The name comes from the words and the voice, so a change to either makes a new clip."""
    key = hashlib.sha1(f"{voice}\n{text}".encode()).hexdigest()[:16]
    out = paths.CLIPS / f"{key}.mp3"
    if not out.exists():
        make_mp3(text, voice, out)
    return out


def play(path: Path, wait: bool = True, delete_after: bool = False) -> subprocess.Popen:
    """Plays an mp3 through Windows' own media player, with no window."""
    cleanup = f";Remove-Item -LiteralPath '{path}' -ErrorAction SilentlyContinue" if delete_after else ""
    script = (
        "Add-Type -AssemblyName PresentationCore;"
        "$p=New-Object System.Windows.Media.MediaPlayer;"
        f"$p.Open([Uri]'{path}');"
        "$i=0;while(-not $p.NaturalDuration.HasTimeSpan -and $i -lt 100){Start-Sleep -Milliseconds 50;$i++};"
        "$d=$p.NaturalDuration.TimeSpan.TotalSeconds;$p.Play();"
        "Start-Sleep -Milliseconds ([math]::Ceiling($d*1000)+300);$p.Close()" + cleanup
    )
    proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script], creationflags=NO_WINDOW
    )
    if wait:
        proc.wait()
    return proc


def stop_answer() -> None:
    """Stops an answer that is still being read aloud."""
    try:
        pid = paths.PLAYER_PID.read_text().strip()
    except OSError:
        return
    if pid.isdigit():
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
    paths.PLAYER_PID.unlink(missing_ok=True)
