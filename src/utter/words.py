"""Turning what was heard into a command, or into the message to type."""

from __future__ import annotations

import re

COMMANDS = {
    "send": {"send", "send it", "send that", "send it now", "send the message"},
    "scratch": {"scratch that", "clear", "clear it", "clear that", "clear the box", "delete that", "start over"},
    "quiet": {"quiet", "be quiet", "stop talking", "shut up", "silence", "mute"},
    "stop": {"stop", "stop working", "stop it", "stop everything", "abort"},
    "cancel": {"cancel", "cancel that", "never mind", "nevermind", "forget it", "forget that"},
    "voice off": {"voice off", "turn voice off", "turn off voice", "turn off the voice", "no voice", "stop speaking"},
    "voice on": {"voice on", "turn voice on", "turn on voice", "turn on the voice", "speak again", "start speaking"},
    "help": {"help", "show help", "hide help", "what can i say", "commands"},
    "repeat": {"repeat that", "repeat", "say that again", "repeat the answer", "what did you say", "say it again"},
    "read back": {"read it back", "read that back", "read back", "read me the message", "what did i say",
                  "read the message"},
}
CHANGE = re.compile(r"^(?:change|replace|correct) (.+?) (?:to|with|into) (.+)$")
SPELL = re.compile(r"^spell(?: it| that)? (.+)$")
FILLERS = re.compile(r"(?:,\s*)?\b(?:um+|uh+|uhm+|erm+|er|ah+|hmm+)\b,?", re.I)

NATO = {
    "alpha": "a", "alfa": "a", "bravo": "b", "charlie": "c", "delta": "d", "echo": "e", "foxtrot": "f",
    "golf": "g", "hotel": "h", "india": "i", "juliet": "j", "juliett": "j", "kilo": "k", "lima": "l",
    "mike": "m", "november": "n", "oscar": "o", "papa": "p", "quebec": "q", "romeo": "r", "sierra": "s",
    "tango": "t", "uniform": "u", "victor": "v", "whiskey": "w", "whisky": "w", "x-ray": "x", "xray": "x",
    "yankee": "y", "zulu": "z",
}
SPOKEN_LETTERS = {
    "ay": "a", "bee": "b", "be": "b", "see": "c", "sea": "c", "dee": "d", "ee": "e", "eff": "f", "gee": "g",
    "aitch": "h", "eye": "i", "jay": "j", "kay": "k", "el": "l", "em": "m", "en": "n", "oh": "o", "pee": "p",
    "queue": "q", "cue": "q", "are": "r", "ess": "s", "tee": "t", "tea": "t", "you": "u", "vee": "v",
    "double-u": "w", "ex": "x", "why": "y", "zed": "z", "zee": "z",
}
SPOKEN_SYMBOLS = {
    "space": " ", "dash": "-", "hyphen": "-", "minus": "-", "underscore": "_", "dot": ".", "period": ".",
    "point": ".", "slash": "/", "backslash": "\\", "at": "@", "colon": ":", "comma": ",", "hash": "#",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9",
}


def plain(text: str, wake_phrases: list[str] = ()) -> str:
    """Lower case, no punctuation, without a leading wake phrase or 'please'."""
    words = " ".join("".join(c for c in text.lower() if c.isalnum() or c in " '-").split())
    for prefix in [p + " " for p in wake_phrases] + ["claude ", "please ", "okay ", "ok "]:
        words = words.removeprefix(prefix)
    return words.removesuffix(" please").strip()


def parse(text: str, wake_phrases: list[str] = ()) -> tuple[str, str]:
    """(command, argument) when the whole of `text` is a command, else ('', '').

    "type <command>" gives ('literal', <command>), so "type stop" types the word "stop".
    """
    words = plain(text, wake_phrases)
    for name, phrases in COMMANDS.items():
        if words in phrases:
            return name, ""
    near = near_command(words)
    if near:
        return near, ""
    if words.startswith("type "):
        rest = words.removeprefix("type ")
        if parse(rest)[0]:
            return "literal", rest
    m = CHANGE.match(words)
    if m and len(m.group(1).split()) <= 6:
        return "change", f"{m.group(1)}\t{m.group(2)}"
    m = SPELL.match(words)
    if m:
        spelled = spell(m.group(1))
        if spelled:
            return "spell", spelled
    return "", ""


def near_command(words: str) -> str:
    """The speech model often mangles short commands ("rea back"). A short utterance that is
    nearly a command phrase counts as that command. Very short words never do ("top" is not "stop")."""
    from difflib import SequenceMatcher

    if len(words) < 6 or len(words.split()) > 4:
        return ""
    best, best_name = 0.0, ""
    for name, phrases in COMMANDS.items():
        for phrase in phrases:
            if len(phrase) < 6:
                continue
            ratio = SequenceMatcher(None, words, phrase).ratio()
            if ratio > best:
                best, best_name = ratio, name
    return best_name if best >= 0.86 else ""


def command_in(text: str, wake_phrases: list[str] = ()) -> str:
    return parse(text, wake_phrases)[0]


def spell(spoken: str) -> str:
    """'m y capital s q l' -> 'mySql'. Unknown words make it not a spelling."""
    out, capital = [], False
    for word in spoken.replace(",", " ").replace(".", " ").split():
        if word in ("capital", "cap", "uppercase"):
            capital = True
            continue
        if len(word) == 1 and word.isalnum():
            ch = word
        elif word in NATO:
            ch = NATO[word]
        elif word in SPOKEN_LETTERS:
            ch = SPOKEN_LETTERS[word]
        elif word in SPOKEN_SYMBOLS:
            ch = SPOKEN_SYMBOLS[word]
        elif word.isalnum():
            ch = word  # the speech model often joins spelled letters into one word: "abc"
        else:
            return ""
        out.append(ch.upper() if capital else ch)
        capital = False
    return "".join(out)


def change(text: str, wrong: str, right: str) -> str | None:
    """`text` with the last `wrong` (any case) changed to `right`, or None when it isn't there."""
    matches = list(re.finditer(r"(?<!\w)" + re.escape(wrong) + r"(?!\w)", text, re.I))
    if not matches:
        return None
    m = matches[-1]
    return text[: m.start()] + right + text[m.end():]


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


def tidy(text: str, remove_fillers: bool, replacements: dict[str, str]) -> str:
    """Fillers out, the person's own replacements in."""
    if remove_fillers:
        text = FILLERS.sub(" ", text)
        text = re.sub(r"\s+([.,!?])", r"\1", re.sub(r"\s{2,}", " ", text)).lstrip(" ,.").rstrip(" ,")
        if text and text[0].islower():
            text = text[0].upper() + text[1:]
    for heard, typed in sorted(replacements.items(), key=lambda kv: len(kv[0]), reverse=True):
        text = re.sub(r"(?<!\w)" + re.escape(heard) + r"(?!\w)", typed.replace("\\", "\\\\"), text, flags=re.I)
    return text


def joined(prefix: str, words: str) -> str:
    return f"{prefix} {words}".strip() if prefix else words


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def _bare(text: str) -> str:
    return " ".join("".join(c for c in text.lower() if c.isalnum() or c == " ").split())


def without_repeats(text: str) -> str:
    """'We'll see you. We'll see you. We'll see you.' -> 'We'll see you.' Whisper loops on noise."""
    out: list[str] = []
    for sentence in _sentences(text):
        if not out or _bare(sentence) != _bare(out[-1]):
            out.append(sentence)
    return " ".join(out)


def only_phantoms(text: str, phantoms: set[str]) -> bool:
    """True when every sentence is one Whisper invents from noise ("Thank you.")."""
    bare = [_bare(s) for s in _sentences(text)]
    return bool(bare) and all(b in phantoms or not b for b in bare)
