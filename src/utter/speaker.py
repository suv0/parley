"""Reads Claude's answers aloud, a part at a time, and takes "more", "skip", "go back", "pause".

The read-aloud hook rewrites each answer for listening and drops it in the inbox folder. Utter
reads the short version straight away, unless you're talking (then it waits until you finish),
and keeps the rest for "more". While one part plays, the next one's audio is made.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from . import settings as paths
from .voice import _remove, cue, make_audio, mark_playing, on_stop, play, stop_player

log = logging.getLogger("utter")
MORE_HINT = "There's more. Say {wake}, more, to hear it."


class Speaker:
    def __init__(self, settings: paths.Settings, busy, speak: bool = True) -> None:
        self.settings = settings
        self.busy = busy  # True while you're talking to Utter: answers wait
        self.speak = speak
        self.lock = threading.Lock()
        self.parts: list[str] = []  # what is being read now, part by part
        self.index = 0  # the part playing or next to play
        self.rest: list[str] = []  # read on "more"
        self.paused = False
        self.changed = threading.Event()  # wakes the reading thread
        self.player = None
        self.playing = ""  # text of the part playing now
        self.last_sent = 0.0  # when you last sent a message by voice
        self.tone = False
        on_stop(self._stopped)  # "quiet" or the tray stopped the answer
        if speak:
            threading.Thread(target=self._run, daemon=True).start()
            threading.Thread(target=self._inbox, daemon=True).start()

    # --- what to read ----------------------------------------------------------------

    def answer(self, short: str, more: list[str]) -> None:
        """A new answer: replaces whatever was being read."""
        wake = self.settings.wake_name
        parts = [short] + ([MORE_HINT.format(wake=wake)] if more else [])
        paths.LAST_ANSWER.write_text(short, encoding="utf-8")  # for "repeat that"
        paths.LAST_MORE.write_text(json.dumps(more), encoding="utf-8")
        self._read(parts, rest=more, tone=True)

    def more(self) -> bool:
        """Resumes a paused or cut-off answer, else reads the rest. False when there's nothing."""
        with self.lock:
            if self.index < len(self.parts) and self.paused:
                self.paused = False
                self.changed.set()
                return True
            rest = self.rest or _saved_more()
            if not rest:
                return False
            self.rest = []
            paths.LAST_MORE.write_text("[]", encoding="utf-8")
        self._read(rest)
        return True

    def repeat(self) -> bool:
        try:
            short = paths.LAST_ANSWER.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        if not short:
            return False
        self._read([short], rest=_saved_more())
        return True

    def say(self, text: str) -> None:
        """Reads any text as an answer ("read it back"), so "quiet" stops it."""
        self._read([text], rest=self.rest)

    def _read(self, parts: list[str], rest: list[str] | None = None, tone: bool = False) -> None:
        self._stop_player()
        with self.lock:
            self.parts, self.index, self.paused = [p for p in parts if p.strip()], 0, False
            if rest is not None:
                self.rest = list(rest)
            self.tone = tone
        self.changed.set()

    # --- moving around ---------------------------------------------------------------

    def skip(self) -> bool:
        with self.lock:
            if self.index >= len(self.parts):
                return False
            self.index += 1
            self.paused = False
        self._stop_player()
        self.changed.set()
        return True

    def back(self) -> bool:
        with self.lock:
            if not self.parts:
                return False
            self.index = max(0, self.index - 1)
            self.paused = False
        self._stop_player()
        self.changed.set()
        return True

    def pause(self) -> bool:
        with self.lock:
            if self.index >= len(self.parts):
                return False
            self.paused = True
        self._stop_player()
        return True

    def quiet(self) -> None:
        with self.lock:
            self.parts, self.index, self.paused = [], 0, False
        self._stop_player()

    def interrupt(self) -> None:
        """You started talking to Utter: stop reading, but keep the place for "more"."""
        with self.lock:
            if self.index < len(self.parts):
                self.paused = True
        self._stop_player()

    def reading(self) -> str:
        return self.playing

    def remaining(self) -> bool:
        with self.lock:
            return self.index < len(self.parts) or bool(self.rest)

    def _stopped(self) -> None:
        with self.lock:
            self.parts, self.index, self.paused = [], 0, False

    def _stop_player(self) -> None:
        player = self.player
        if player is not None and player.poll() is None:
            stop_player()

    # --- the reading thread ----------------------------------------------------------

    def _run(self) -> None:
        ready: dict[str, Path] = {}  # text -> audio made ahead
        while True:
            self.changed.wait(timeout=0.5)
            self.changed.clear()
            while True:
                with self.lock:
                    if self.paused or self.index >= len(self.parts):
                        break
                    text, nxt = self.parts[self.index], self.parts[self.index + 1:self.index + 2]
                    index, parts, tone = self.index, self.parts, self.tone
                    self.tone = False
                if self.busy():
                    time.sleep(0.3)  # you're talking: wait until you're done
                    continue
                try:
                    audio = ready.pop(text, None) or make_audio(text, self.settings, _stem())
                except Exception:
                    log.exception("couldn't make the answer's speech")
                    with self.lock:
                        if self.parts is parts and self.index == index:
                            self.index += 1
                    continue
                for future in nxt:  # make the next part while this one plays
                    threading.Thread(target=self._prepare, args=(future, ready), daemon=True).start()
                if tone and self.settings.cue_sounds:
                    cue("answer")
                self.playing = text
                self.player = play(audio, wait=False, delete_after=True)
                mark_playing(self.player.pid, audio, text)
                self.player.wait()
                self.playing = ""
                paths.SPEAKING.unlink(missing_ok=True)
                _remove(audio)
                with self.lock:
                    if self.parts is parts and self.index == index and not self.paused:
                        self.index += 1  # finished: on to the next part

    def _prepare(self, text: str, ready: dict) -> None:
        try:
            ready[text] = make_audio(text, self.settings, _stem())
        except Exception:
            pass

    # --- answers from the hook -------------------------------------------------------

    def _inbox(self) -> None:
        paths.INBOX.mkdir(parents=True, exist_ok=True)
        while True:
            time.sleep(0.3)
            found = sorted(paths.INBOX.glob("*.json"))
            if not found:
                continue
            newest = found[-1]
            try:
                item = json.loads(newest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                item = None
            for path in found:
                path.unlink(missing_ok=True)
            if not item or paths.VOICE_OFF.exists():
                continue
            if self.settings.read_answers == "mine" and time.time() - self.last_sent > 15 * 60:
                log.info("an answer arrived, not read: only answers to voice messages are read")
                continue
            more = item.get("more", [])
            log.info("reading an answer (%s, %d more parts%s)", "rewritten by Claude" if item.get("by") == "claude"
                     else "plain", len(more), f", {len(found) - 1} older skipped" if len(found) > 1 else "")
            self.answer(item.get("short", ""), more)


def _saved_more() -> list[str]:
    try:
        return [str(p) for p in json.loads(paths.LAST_MORE.read_text(encoding="utf-8"))]
    except (OSError, ValueError):
        return []


def _stem() -> Path:
    return paths.STATE / f"answer-{time.time_ns()}"
