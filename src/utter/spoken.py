"""Turning Claude's written answer into what a person would say out loud.

Claude writes for the screen: code, links, tables, "PR #456". Read out word for word, that is
hard to follow. A fast Claude model rewrites each answer for listening: the outcome first,
things described instead of numbered, and the rest only if you ask for more. Without a way to
reach Claude, or when it is slow, the answer is cleaned up with rules instead.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass

from . import settings as paths

log = logging.getLogger("utter")
NO_WINDOW = 0x08000000
REWRITING = "UTTER_REWRITING"  # set while Claude rewrites an answer, so the read-aloud hook skips that run

PROMPT = """You turn a coding assistant's written reply into speech for someone who can't see the screen.
Write what a helpful colleague would say out loud.
- Start with the outcome in one or two short sentences.
- Describe things instead of reading identifiers: "the pull request that adds the demo animation", \
not "PR 2"; "the settings file", not a path; "a link to the docs", not a web address. Never read \
hashes, IDs, paths, web addresses, code or symbols.
- Say what code does in plain words instead of reading it.
- Round numbers that don't need to be exact.
- Keep every decision, warning and next step. If the reply asks the listener something, end with that question.
- Plain sentences only: no lists, markdown, emoji or headings.
Reply in exactly this form:
<short>two to four sentences: the outcome, and anything needed from the listener</short>
<more>the rest of the reply in the same spoken style, in short paragraphs, or nothing if the short part covers it</more>"""


@dataclass
class Spoken:
    short: str  # read straight away
    more: list[str]  # read on "more", one paragraph at a time
    by: str = "rules"  # "claude" when Claude rewrote it


def for_listening(written: str, s: paths.Settings) -> Spoken:
    """The spoken version of `written`."""
    if s.spoken_answers == "rewrite":
        try:
            spoken = parse(rewrite(written, s))
            if spoken.short:
                return spoken
            log.info("the rewrite came back empty; using the plain version")
        except Exception as error:
            log.info("couldn't rewrite the answer (%s); using the plain version", error)
    return split(plain(written))


def rewrite(written: str, s: paths.Settings) -> str:
    """Claude's spoken version, through the API when ANTHROPIC_API_KEY is set, else the claude command."""
    written = written[:20000]
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        body = json.dumps({
            "model": s.rewrite_model, "max_tokens": 1500, "system": PROMPT,
            "messages": [{"role": "user", "content": written}],
        }).encode()
        request = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json",
        })
        with urllib.request.urlopen(request, timeout=s.rewrite_seconds) as response:
            data = json.load(response)
        return "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    claude = shutil.which("claude")
    if not claude:
        raise RuntimeError("no ANTHROPIC_API_KEY and no claude command")
    done = subprocess.run(
        # Hooks off, so this run doesn't trigger Utter's own read-aloud hook again.
        [claude, "-p", "--model", s.rewrite_model, "--settings", json.dumps({"disableAllHooks": True}),
         "--system-prompt", PROMPT],
        input=written, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=s.rewrite_seconds, creationflags=NO_WINDOW, env={**os.environ, REWRITING: "1"},
    )
    if done.returncode != 0:
        said = [line for line in (done.stderr + done.stdout).splitlines()
                if line.strip() and "hooks module not loaded" not in line]  # plugin notices, not the error
        raise RuntimeError((said[-1] if said else "the claude command failed").strip()[:200])
    return done.stdout


def parse(reply: str) -> Spoken:
    short = re.search(r"<short>(.*?)</short>", reply, re.S)
    more = re.search(r"<more>(.*?)</more>", reply, re.S)
    if not short:  # no tags: treat the whole reply as speech
        return split(plain(reply), by="claude")
    return Spoken(tidy(short.group(1)), paragraphs(more.group(1) if more else ""), by="claude")


def tidy(text: str) -> str:
    text = re.sub(r"[*_#`>|]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def paragraphs(text: str, longest: int = 600) -> list[str]:
    """Short paragraphs to read one at a time. Long ones are split at sentences."""
    out = []
    for block in re.split(r"\n\s*\n|\n", text):
        block = tidy(block)
        while len(block) > longest:
            cut = max(block.rfind(". ", 0, longest), block.rfind("? ", 0, longest), block.rfind("! ", 0, longest))
            cut = cut + 1 if cut > longest // 3 else longest
            out.append(block[:cut].strip())
            block = block[cut:].strip()
        if block:
            out.append(block)
    return out


def split(text: str, by: str = "rules", short_chars: int = 300) -> Spoken:
    """The first few sentences now, the rest on request."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    short = []
    while sentences and (not short or len(" ".join(short)) + len(sentences[0]) <= short_chars):
        short.append(sentences.pop(0))
    return Spoken(tidy(" ".join(short)), paragraphs(" ".join(sentences)), by=by)


def plain(text: str) -> str:
    """The written answer without code, tables, links and markdown, ready to speak."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)  # code blocks
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") or re.fullmatch(r"[-|: ]+", s or "x"):
            continue  # tables
        s = s.lstrip(">").strip()
        s = re.sub(r"^#{1,6}\s*", "", s)
        s = re.sub(r"^([-*+]|\d+\.)\s+", "", s)
        if s and not re.search(r"[.!?:]$", s):
            s += "."  # list items and headings end where they end
        lines.append(s)
    text = "\n".join(lines)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # links keep their words
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)
    text = re.sub(r"\b[0-9a-f]{7,40}\b", "", text)  # commit hashes
    text = text.replace("→", " to ").replace("·", ",").replace("#", " number ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{2,}", "\n", text).strip()
