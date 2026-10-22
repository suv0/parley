"""Turning what was heard into a command, or into the message to type."""

from __future__ import annotations

COMMANDS = {
    "send": {"send", "send it", "send that", "send it now", "send the message"},
    "scratch": {"scratch that", "clear", "clear it", "clear that", "clear the box", "delete that", "start over"},
    "quiet": {"quiet", "be quiet", "stop talking", "shut up", "silence", "mute"},
    "stop": {"stop", "stop working", "cancel", "stop it", "stop everything", "abort"},
    "voice off": {"voice off", "turn voice off", "turn off voice", "turn off the voice", "no voice", "stop speaking"},
    "voice on": {"voice on", "turn voice on", "turn on voice", "turn on the voice", "speak again", "start speaking"},
    "help": {"help", "show help", "hide help", "what can i say", "commands"},
}


def plain(text: str, wake_phrases: list[str] = ()) -> str:
    """Lower case, no punctuation, without a leading wake phrase or 'please'."""
    words = " ".join("".join(c for c in text.lower() if c.isalnum() or c in " '").split())
    for prefix in [p + " " for p in wake_phrases] + ["claude ", "please ", "okay "]:
        words = words.removeprefix(prefix)
    return words.removesuffix(" please").strip()


def command_in(text: str, wake_phrases: list[str] = ()) -> str:
    """The command name when the whole of `text` is a command, else ''."""
    words = plain(text, wake_phrases)
    for name, phrases in COMMANDS.items():
        if words in phrases:
            return name
    return ""


def ends_with_send(text: str, send_phrases: list[str]) -> bool:
    """True when a message (not a bare send phrase) ends with a send phrase."""
    words = plain(text)
    return any(words.endswith(p) and len(words) > len(p) for p in send_phrases)


def strip_send_phrase(text: str, send_phrases: list[str]) -> str:
    """The message without the send phrase at its end."""
    trimmed = text.rstrip(" .!?,")
    lower = trimmed.lower()
    for phrase in sorted(send_phrases, key=len, reverse=True):
        if lower.endswith(phrase) and len(lower) > len(phrase) + 3:
            cut = trimmed[: len(trimmed) - len(phrase)].rstrip(" .!?,")
            return cut + "." if cut and cut[-1].isalnum() else cut
    return text


def joined(prefix: str, words: str) -> str:
    return f"{prefix} {words}".strip() if prefix else words
