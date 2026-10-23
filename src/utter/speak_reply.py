"""Claude Code Stop hook: reads Claude's last answer aloud, rewritten for listening.

`utter setup` adds it to ~/.claude/settings.json as an async hook, so Claude never waits for it.
A fast Claude model rewrites the answer for the ear (see spoken.py). When Utter is running,
the spoken answer goes to Utter, which reads it a part at a time and takes "more", "skip" and
"pause"; otherwise this hook reads the short version itself.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from . import settings as paths
from .spoken import REWRITING, for_listening
from .voice import _running, make_audio, play_as_answer


def last_reply(payload: dict) -> str:
    text = payload.get("last_assistant_message")
    if isinstance(text, str) and text.strip():
        return text
    path = payload.get("transcript_path")
    if not path or not Path(path).exists():
        return ""
    last = ""
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        content = (entry.get("message") or {}).get("content")
        if entry.get("type") == "assistant" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").strip():
                    last = block["text"]
    return last


def mic_is_open() -> bool:
    try:
        return time.time() - float(paths.LISTENING_FLAG.read_text() or 0) < 120
    except (OSError, ValueError):
        return False


def utter_running() -> bool:
    try:
        pid = int((paths.STATE / "app.pid").read_text().strip())
    except (OSError, ValueError):
        return False
    return _running(pid)


def main() -> None:
    if os.environ.get(REWRITING):
        return  # Claude rewriting an answer for Utter: not an answer to read
    settings = paths.load()
    if not settings.speak_replies or paths.VOICE_OFF.exists():
        return
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    written = last_reply(payload)
    if len(written.strip()) < 3:
        return
    spoken = for_listening(written, settings)
    if len(spoken.short) < 3:
        return
    paths.STATE.mkdir(parents=True, exist_ok=True)
    if utter_running():
        paths.INBOX.mkdir(parents=True, exist_ok=True)
        item = paths.INBOX / f"{time.time_ns()}.json"
        temp = item.with_suffix(".tmp")
        temp.write_text(json.dumps({"short": spoken.short, "more": spoken.more, "by": spoken.by}), encoding="utf-8")
        temp.replace(item)  # whole, or not there yet
        return
    paths.LAST_ANSWER.write_text(spoken.short, encoding="utf-8")  # for "repeat that"
    paths.LAST_MORE.write_text(json.dumps(spoken.more), encoding="utf-8")
    audio = make_audio(spoken.short, settings, paths.STATE / f"answer-{os.getpid()}")
    if mic_is_open():  # never talk while Utter is recording you; the mic would hear it
        audio.unlink(missing_ok=True)
        return
    play_as_answer(audio, delete_after=True, text=spoken.short)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # never disturb the Claude session over speech
        pass
