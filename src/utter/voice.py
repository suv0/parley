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
import time
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


def play_as_answer(path: Path, delete_after: bool = False, text: str = "") -> None:
    """Plays an answer so that "quiet" and the next answer can stop it. `text` is what it says,
    so the wake check can tell Utter's own voice from yours."""
    stop_answer()
    player = play(path, wait=False, delete_after=delete_after)
    # The file goes on the second line so stopping the player early can still delete it.
    paths.PLAYER_PID.write_text(f"{player.pid}\n{path}" if delete_after else str(player.pid))
    paths.SPEAKING.write_text(text, encoding="utf-8")


def speaking() -> str:
    """The text of the answer being read aloud right now, or "" when nothing is playing."""
    try:
        pid = paths.PLAYER_PID.read_text().split("\n")[0].strip()
        text = paths.SPEAKING.read_text(encoding="utf-8")
    except OSError:
        return ""
    return text if pid.isdigit() and _running(int(pid)) else ""


def _running(pid: int) -> bool:
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    try:
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def stop_answer() -> None:
    """Stops an answer that is still being read aloud, and deletes its audio if it was a one-off."""
    try:
        pid, _, audio = paths.PLAYER_PID.read_text().strip().partition("\n")
    except OSError:
        return
    if pid.isdigit():
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
    paths.PLAYER_PID.unlink(missing_ok=True)
    paths.SPEAKING.unlink(missing_ok=True)
    if audio:
        _remove(Path(audio))


def _remove(path: Path) -> None:
    for _ in range(20):  # the stopped player can hold the file for a moment after it exits
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.05)
        except OSError:
            return


def remove_old_answers(older_than: float = 3600) -> None:
    """Deletes answer audio left over from a crash or an older Utter. Cached clips stay."""
    cutoff = time.time() - older_than
    for pattern in ("answer-*.mp3", "answer-*.wav", "spoken-*.mp3", "spoken-*.wav"):
        for path in paths.STATE.glob(pattern):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass


# --- beeps --------------------------------------------------------------------------

CUES = {
    "start": [(660, 0.07), (880, 0.09)],  # listening
    "stop": [(880, 0.07), (660, 0.09)],  # done listening
    "error": [(330, 0.18)],
    "cancel": [(587, 0.06), (440, 0.12)],  # back to waiting, nothing typed
    "thinking": [(392, 0.05), (0, 0.06), (392, 0.05)],  # sent; Claude is working
    "answer": [(523, 0.05), (784, 0.08)],  # an answer is about to be read
}


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
