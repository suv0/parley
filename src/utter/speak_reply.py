"""Claude Code Stop hook: reads a short, plain version of Claude's last answer aloud.

`utter setup` adds it to ~/.claude/settings.json as an async hook, so Claude never waits for it.
It drops code, tables, links and markdown, and a new answer stops the one still playing.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from . import settings as paths
from .voice import make_audio, play_as_answer


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


def to_speech(text: str, max_chars: int) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)  # code blocks
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") or re.fullmatch(r"[-|: ]+", s or "x"):
            continue  # tables
        s = s.lstrip(">").strip()
        s = re.sub(r"^#{1,6}\s*", "", s)
        s = re.sub(r"^([-*+]|\d+\.)\s+", "", s)
        lines.append(s)
    text = "\n".join(lines)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # links keep their words
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)
    text = text.replace("→", " to ").replace("·", ",").replace("#", " number ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    if len(text) > max_chars:
        cut = text[:max_chars]
        end = max(cut.rfind(". "), cut.rfind("\n"))
        text = cut[: end + 1] if end > max_chars // 4 else cut
    return text


def mic_is_open() -> bool:
    try:
        return time.time() - float(paths.LISTENING_FLAG.read_text() or 0) < 120
    except (OSError, ValueError):
        return False


def main() -> None:
    settings = paths.load()
    if not settings.speak_replies or paths.VOICE_OFF.exists():
        return
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    speech = to_speech(last_reply(payload), settings.max_spoken_chars)
    if len(speech) < 3:
        return
    paths.STATE.mkdir(parents=True, exist_ok=True)
    paths.LAST_ANSWER.write_text(speech, encoding="utf-8")  # for "repeat that"
    audio = make_audio(speech, settings, paths.STATE / f"answer-{os.getpid()}")
    if mic_is_open():  # never talk while Utter is recording you; the mic would hear it
        audio.unlink(missing_ok=True)
        return
    play_as_answer(audio, delete_after=True, text=speech)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # never disturb the Claude session over speech
        pass
