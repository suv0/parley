"""Was "Hey Claude" really said to Utter, or did a TV, a video or Utter's own voice say it?

The wake recognizer only knows a few phrases, so it maps a lot of other speech onto them. Two
checks catch most of those false wakes:

- You say the wake phrase on its own: the sound just before and just after it is clearly quieter
  than the phrase. A line in a film or a video sits inside more speech at the same loudness.
- Utter's own answers are read through the speakers. While an answer that mentions the wake
  name is playing, a spoken wake can only be that answer.
"""

from __future__ import annotations

from collections import deque

import numpy as np

RATE = 16000
BEFORE = (1.0, 0.15)  # seconds before the phrase starts: from, to
AFTER = (0.15, 0.8)  # seconds after the phrase ends: from, to
RATIO = 0.5  # the loudest sound around the phrase must stay under this share of the phrase's


def level(block: np.ndarray) -> float:
    return float(np.sqrt(np.mean((block.astype(np.float32) / 32768) ** 2)))


class Surroundings:
    """Remembers how loud the last few seconds were, on the wake recognizer's clock."""

    def __init__(self, seconds: float = 8.0, block_seconds: float = 0.1) -> None:
        self.levels: deque[tuple[float, float]] = deque(maxlen=int(seconds / block_seconds))
        self.fed = 0  # samples given to the recognizer since it was reset

    def reset(self) -> None:
        self.levels.clear()
        self.fed = 0

    def add(self, block: np.ndarray) -> None:
        self.levels.append((self.fed / RATE, level(block)))
        self.fed += len(block)

    def loudness(self, start: float, end: float) -> float | None:
        """The loudest level from `start` to `end` seconds, or None when none of it is known.
        The peak, not the average: a short pause between two lines of a film still has a
        loud line on each side."""
        found = [lvl for at, lvl in self.levels if start <= at < end]
        return max(found) if found else None

    def said_alone(self, words: list[dict], floor: float) -> bool:
        """True when the phrase stands out from the sound around it. `words` are the recognizer's
        words with their start and end times; `floor` is the level that counts as talking."""
        if not words:
            return False
        start, end = words[0]["start"], words[-1]["end"]
        if words[0]["word"] == "[unk]" and len(words) > 1:
            # An unrecognized word can stretch back over earlier speech; "hey" is about half a second.
            start = max(start, words[1]["start"] - 0.5)
        phrase = self.loudness(start, max(end, start + 0.1))
        if not phrase or phrase < floor:
            return False
        limit = max(floor, RATIO * phrase)
        for around in (self.loudness(start - BEFORE[0], start - BEFORE[1]),
                       self.loudness(end + AFTER[0], end + AFTER[1])):
            if around is not None and around >= limit:
                return False
        return True


def find(words: list[dict], wake_phrases: list[str]) -> list[dict]:
    """The words of a wake phrase inside what the recognizer heard, or []. With a TV or other
    voices behind you there's no gap, so "Hey Claude" arrives inside a longer utterance. The
    recognizer often misses the "hey" but rarely the name, so "[unk] claude" counts too."""
    said = [w["word"] for w in words]
    wanted = [p.split() for p in wake_phrases if len(p.split()) > 1]
    found = []
    for i in range(len(said)):
        for phrase in wanted:
            if said[i:i + len(phrase)] == phrase:
                found.append(words[i:i + len(phrase)])
        if i + 1 < len(said) and said[i] == "[unk]" and said[i + 1] in names(wake_phrases):
            found.append(words[i:i + 2])
    return found[-1] if found else []  # the last one: the one just said


def names(wake_phrases: list[str]) -> set[str]:
    """The name part of each wake phrase: "hey claude" -> "claude"."""
    return {p.split()[-1] for p in wake_phrases if p.split()}


def mentions(text: str, wake_phrases: list[str]) -> bool:
    words = {"".join(c for c in w if c.isalpha()) for w in text.lower().split()}
    return bool(words & names(wake_phrases))
