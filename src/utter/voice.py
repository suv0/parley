"""Speaking and sounds: short spoken replies ("Sent."), beeps, and stopping an answer mid-sentence.

Two voices: Microsoft Edge's natural online voices, or the offline voices built into Windows.
If the Edge voice can't be reached, the Windows voice speaks instead.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import struct
import subprocess
import wave
from pathlib import Path

from . import settings as paths

NO_WINDOW = 0x08000000
log = logging.getLogger("utter")


def ps_quote(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _edge(text: str, s: paths.Settings, out: Path) -> None:
    import edge_tts

    rate = f"{s.speaking_rate:+d}%"
    asyncio.run(edge_tts.Communicate(text, s.voice, rate=rate).save(str(out)))


def _windows(text: str, s: paths.Settings, out: Path) -> None:
    rate = max(-10, min(10, round(s.speaking_rate / 10)))
    pick = ""
    if s.windows_voice:
        pick = (
            f"$v=$t.GetInstalledVoices()|%{{$_.VoiceInfo.Name}}|?{{$_ -like ('*'+{ps_quote(s.windows_voice)}+'*')}}"
            "|Select-Object -First 1;if($v){$t.SelectVoice($v)};"
        )
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$t=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"{pick}$t.Rate={rate};$t.SetOutputToWaveFile({ps_quote(out)});"
        f"$t.Speak([IO.File]::ReadAllText({ps_quote(out.with_suffix('.txt'))}));$t.Dispose()"
    )
    out.with_suffix(".txt").write_text(text, encoding="utf-8")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       check=True, capture_output=True, creationflags=NO_WINDOW, timeout=120)
    finally:
        out.with_suffix(".txt").unlink(missing_ok=True)


def make_audio(text: str, s: paths.Settings, stem: Path) -> Path:
    """Speech for `text` as stem.mp3 (Edge) or stem.wav (Windows). Returns the file made."""
    stem.parent.mkdir(parents=True, exist_ok=True)
    if s.voice_engine != "windows":
        out = stem.with_suffix(".mp3")
        try:
            _edge(text, s, out)
            return out
        except Exception:
            log.warning("Edge voice unavailable; using the Windows voice", exc_info=True)
            out.unlink(missing_ok=True)
    out = stem.with_suffix(".wav")
    _windows(text, s, out)
    return out


def clip(text: str, s: paths.Settings) -> Path:
    """A cached recording of `text`. Its name comes from the words, voice and speed, so a change makes a new one."""
    voice = s.windows_voice if s.voice_engine == "windows" else s.voice
    key = hashlib.sha1(f"{s.voice_engine}\n{voice}\n{s.speaking_rate}\n{text}".encode()).hexdigest()[:16]
    for found in paths.CLIPS.glob(f"{key}.*"):
        return found
    return make_audio(text, s, paths.CLIPS / key)


def play(path: Path, wait: bool = True, delete_after: bool = False) -> subprocess.Popen:
    """Plays an mp3 or wav through Windows' own media player, with no window."""
    cleanup = f";Remove-Item -LiteralPath {ps_quote(path)} -ErrorAction SilentlyContinue" if delete_after else ""
    script = (
        "Add-Type -AssemblyName PresentationCore;"
        "$p=New-Object System.Windows.Media.MediaPlayer;"
        f"$p.Open([Uri]{ps_quote(path)});"
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


def play_as_answer(path: Path, delete_after: bool = False) -> None:
    """Plays an answer so that "quiet" and the next answer can stop it."""
    stop_answer()
    player = play(path, wait=False, delete_after=delete_after)
    paths.PLAYER_PID.write_text(str(player.pid))


def stop_answer() -> None:
    """Stops an answer that is still being read aloud."""
    try:
        pid = paths.PLAYER_PID.read_text().strip()
    except OSError:
        return
    if pid.isdigit():
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
    paths.PLAYER_PID.unlink(missing_ok=True)


# --- beeps --------------------------------------------------------------------------

CUES = {"start": [(660, 0.07), (880, 0.09)], "stop": [(880, 0.07), (660, 0.09)], "error": [(330, 0.18)]}


def _cue_file(name: str) -> Path:
    out = paths.CLIPS / f"cue-{name}.wav"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        rate, frames = 22050, bytearray()
        for freq, seconds in CUES[name]:
            n = int(rate * seconds)
            for i in range(n):
                fade = min(1.0, i / 200, (n - i) / 200)
                frames += struct.pack("<h", int(9000 * fade * math.sin(2 * math.pi * freq * i / rate)))
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(bytes(frames))
    return out


def cue(name: str) -> None:
    """A short beep, played right here (no PowerShell), so it is quick."""
    import winsound

    try:
        winsound.PlaySound(str(_cue_file(name)), winsound.SND_FILENAME)
    except Exception:
        log.exception("cue failed")
