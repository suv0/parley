"""The listening loop: wait for the wake phrase (or the shortcut), then type what you say.

1. "Hey Claude" (or Ctrl+Alt+H) -> a beep.
2. You talk. In the Claude app the words appear live in the box; elsewhere, on the strip.
3. "...send it" sends (or the shortcut again, or a pause in "pause" send mode).
   15 seconds of quiet leaves the words typed, unsent.
A bare command after the wake phrase ("scratch that", "repeat that", ...) runs instead.

Time is measured in audio, not on the wall clock, so the same sound always gives the same
result (and tests can feed recorded speech faster than real time).
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time

import numpy as np

from . import settings as paths
from .targets import Hands, clipboard_text, restore_clipboard
from .voice import clip, cue, make_audio, play, play_as_answer, remove_old_answers, stop_answer
from .words import change, ends_with_send, is_wake, joined, parse, strip_send_phrase, tidy

log = logging.getLogger("utter")

RATE = 16000
BLOCK = 1600  # 0.1 s
LIVE_EVERY = 1.0  # seconds of audio between live updates
UNCLEAR = -0.85  # average log-probability below which Utter isn't sure it heard right

paused = threading.Event()
stopping = threading.Event()
ui_events: queue.Queue[tuple[str, str]] = queue.Queue()  # (kind, text) for the strip and tray

SAYINGS = {
    "yes": "Yes?",
    "sent": "Sent.",
    "left": "I left it there. Say {wake}, send it, when you're ready.",
    "nothing": "I didn't hear anything.",
    "cleared": "Cleared.",
    "empty": "There's nothing to send.",
    "nowindow": "I can't find the Claude app. Open it, then try again.",
    "noclick": "Click the Claude message box once, then try again.",
    "nowhere": "I don't know where to type. Click where you want the words, then try again.",
    "failed": "Something went wrong typing that.",
    "stopped": "Stopped.",
    "voiceoff": "Okay, I'll stop reading my answers. Say voice on to bring them back.",
    "voiceon": "Voice is back on.",
    "nomic": "I can't use the microphone. Check the Windows microphone privacy setting.",
    "unclear": "I'm not sure I heard that right, so I didn't send it. Here's what I typed.",
    "changed": "Changed.",
    "notfound": "I couldn't find that in the box.",
    "notsupported": "That only works in the Claude app's message box.",
    "noanswer": "There's no answer to repeat yet.",
    "typed": "Typed.",
}
STATUS = {
    "nowindow": "Can't find the Claude app",
    "noclick": "Click a Claude message box once",
    "nowhere": "Click where you want the words",
    "empty": "Nothing to send",
    "failed": "Couldn't type that",
    "notfound": "Couldn't find that word",
    "notsupported": "Only in the Claude app's box",
    "noanswer": "No answer to repeat yet",
}


class Assistant:
    def __init__(self, settings: paths.Settings, hands=None, speak: bool = True) -> None:
        self.settings = settings
        self.hands = hands
        self.speak = speak  # False in tests: no beeps or spoken replies
        self.idle_text = f"Say “{settings.wake_name}”" + (f" or press {settings.hotkey}" if settings.hotkey else "")
        self.audio: queue.Queue[np.ndarray] = queue.Queue()
        self.ears = threading.Event()  # set = keep what the mic hears
        self.hotkey = threading.Event()  # set when the shortcut is pressed

    # --- status and sound ----------------------------------------------------------

    def show(self, state: str, text: str, live: str = "") -> None:
        """state: idle | listening | working | paused | problem"""
        log.info("status: %s | %s%s", state, text, f" | {live}" if live else "")
        ui_events.put(("status", f"{state}\t{text}\t{live}"))

    def say(self, key: str, wait: bool = True) -> None:
        if not self.speak:
            return
        try:
            text = SAYINGS[key].format(wake=self.settings.wake_name)
            play(clip(text, self.settings), wait=wait)
        except Exception:
            log.exception("say failed")

    def say_text(self, text: str) -> None:
        """Reads any text aloud, as an answer (so "quiet" stops it)."""
        if not self.speak or not text.strip():
            return
        try:
            audio = make_audio(text, self.settings, paths.STATE / f"spoken-{time.time_ns()}")
            play_as_answer(audio, delete_after=True)
        except Exception:
            log.exception("reading aloud failed")

    def beep(self, name: str) -> None:
        if self.speak and self.settings.cue_sounds:
            cue(name)

    def problem(self, name: str) -> None:
        name = name if name in SAYINGS else "failed"
        self.show("problem", STATUS.get(name, SAYINGS[name]))
        self.beep("error")
        self.say(name)

    # --- start ---------------------------------------------------------------------

    def load_models(self) -> bool:
        import vosk
        from faster_whisper import WhisperModel

        s = self.settings
        have = lambda name: any(paths.WHISPER_MODELS.glob(f"models--*faster-whisper-{name}"))  # noqa: E731
        if not paths.VOSK_MODEL.exists() or not have(s.model("live")) or not have(s.model("final")):
            self.show("problem", "Speech models missing. Run install.ps1 again")
            return False
        load = lambda name: WhisperModel(  # noqa: E731
            name, device="cpu", compute_type="int8", download_root=str(paths.WHISPER_MODELS), local_files_only=True
        )
        self.live_model, self.final_model = load(s.model("live")), load(s.model("final"))
        vosk.SetLogLevel(-1)
        self.wake = vosk.KaldiRecognizer(
            vosk.Model(str(paths.VOSK_MODEL)), RATE, json.dumps(s.wake_phrases + ["[unk]"])
        )
        return True

    def run(self) -> None:
        import sounddevice as sd

        from . import hotkey

        s = self.settings
        self.show("working", "Starting up")
        remove_old_answers()
        if not self.load_models():
            return
        if self.speak:
            for key in SAYINGS:  # make every spoken reply once, so none waits on the network later
                try:
                    clip(SAYINGS[key].format(wake=s.wake_name), s)
                except Exception:
                    log.exception("could not make the %s clip", key)
        self.hands = self.hands or Hands(stopping)
        if s.hotkey:
            trouble = hotkey.listen(s.hotkey, self.hotkey)
            if trouble:
                taken = "taken by another app" if "already used" in trouble else "not understood"
                self.idle_text = f"Say “{s.wake_name}” (shortcut {s.hotkey} {taken})"
        self.ears.set()

        def on_audio(indata, frames, t, status):
            if self.ears.is_set():
                self.audio.put(indata[:, 0].copy())

        try:
            stream = sd.InputStream(
                samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK, callback=on_audio,
                device=s.microphone or None,
            )
            stream.start()
        except Exception:
            log.exception("microphone")
            self.show("problem", "Can't use the microphone. See Help in the tray menu")
            self.say("nomic")
            return
        with stream:
            self.show("idle", self.idle_text)
            log.info("listening for the wake phrase")
            self.listen()

    def listen(self, until_empty: bool = False) -> None:
        """Waits for the wake phrase or the shortcut, then takes one message. `until_empty` is for tests."""
        while not stopping.is_set():
            woke = ""
            if self.hotkey.is_set():
                self.hotkey.clear()
                woke = "shortcut"
            else:
                try:
                    block = self.audio.get(timeout=0.2)
                except queue.Empty:
                    if until_empty:
                        return
                    continue
                if paused.is_set() or not self.wake.AcceptWaveform(block.tobytes()):
                    continue
                heard = json.loads(self.wake.Result()).get("text", "")
                if not is_wake(heard, self.settings.wake_phrases):
                    continue
                woke = heard
            if paused.is_set():
                continue
            log.info("wake: %s", woke)
            try:
                self.one_message()
            except Exception:
                log.exception("message failed")
                self.show("problem", "Something went wrong. Try again")
            self.wake.Reset()
            self.hotkey.clear()
            if not until_empty:
                self.drain()
            self.ears.set()
            if not paused.is_set():
                ui_events.put(("idle-later", self.idle_text))

    def drain(self) -> None:
        while not self.audio.empty():
            self.audio.get_nowait()

    # --- one message ---------------------------------------------------------------

    def one_message(self) -> None:
        s = self.settings
        stop_answer()
        paths.STATE.mkdir(parents=True, exist_ok=True)
        paths.LISTENING_FLAG.write_text(str(time.time()))
        saved_clipboard = clipboard_text()
        try:
            self.ears.clear()
            target = self.hands.pick(s.target)
            if s.cue_sounds:
                self.beep("start")
            else:
                self.say("yes")
            problem, prefix = target.read()
            if problem:
                self.problem(problem)
                return
            ending = f"say “{s.send_phrases[0]}”" if s.send_phrases else "press the shortcut"
            listening = f"Listening → {target.name}. When done, {ending}"
            self.show("listening", listening)
            if self.speak:
                self.drain()
            self.ears.set()
            how, chunks, live = self.hear(target, prefix, listening)
            self.ears.clear()
            if self.speak and s.cue_sounds:
                self.beep("stop")
            self.finish(target, prefix, how, chunks, live)
        finally:
            restore_clipboard(saved_clipboard)
            paths.LISTENING_FLAG.unlink(missing_ok=True)

    def hear(self, target, prefix: str, listening: str) -> tuple[str, list[np.ndarray], str]:
        """Collects the message. How it ended: send | pause | leave | command | nothing."""
        s = self.settings
        chunks: list[np.ndarray] = []
        heard_at = None  # seconds of audio at the last loud block
        next_update = LIVE_EVERY
        live = ""
        last_audio = time.time()
        while True:
            try:
                block = self.audio.get(timeout=0.5)
            except queue.Empty:
                if time.time() - last_audio > 5:  # the microphone stopped
                    return ("leave" if chunks else "nothing"), chunks, live
                continue
            last_audio = time.time()
            chunks.append(block)
            now = len(chunks) * BLOCK / RATE
            if float(np.sqrt(np.mean((block.astype(np.float32) / 32768) ** 2))) > s.speaking_level:
                heard_at = now
            if self.hotkey.is_set():
                self.hotkey.clear()
                return ("send" if heard_at is not None else "nothing"), chunks, live
            if heard_at is None:
                if now > s.nothing_heard_seconds:
                    return "nothing", chunks, live
                continue
            quiet = now - heard_at
            if now >= next_update:
                next_update = now + LIVE_EVERY
                fresh, _ = self.transcribe(self.live_model, chunks, beam_size=1)
                if fresh and fresh != live:
                    live = fresh
                    if target.live_typing and not parse(live, s.wake_phrases)[0]:
                        target.write(joined(prefix, tidy(live, s.remove_fillers, s.replacements)))
                    self.show("listening", listening, live)
                if ends_with_send(live, s.send_phrases):
                    return "send", chunks, live
            is_command = bool(live and parse(live, s.wake_phrases)[0])
            if is_command and quiet >= s.command_pause_seconds:
                return "command", chunks, live
            if s.send_mode == "pause" and live and not is_command and quiet >= s.pause_seconds:
                return "pause", chunks, live
            if quiet >= s.quiet_seconds or now > s.max_message_seconds:
                return "leave", chunks, live

    def finish(self, target, prefix: str, how: str, chunks: list[np.ndarray], live: str) -> None:
        s = self.settings
        if how == "nothing":
            target.write(prefix)
            self.show("problem", "I didn't hear anything")
            self.say("nothing")
            return
        self.show("working", "Getting your words right")
        final, sureness = self.transcribe(self.final_model, chunks, beam_size=5)
        final = final or live
        log.info("final: %r (%s, sureness %.2f)", final, how, sureness)
        command, arg = parse(final, s.wake_phrases)
        if not command and how == "command":
            command, arg = parse(live, s.wake_phrases)
        if command and command != "literal":
            self.command(command, arg, target, prefix)
            return
        text = arg if command == "literal" else tidy(strip_send_phrase(final, s.send_phrases), s.remove_fillers,
                                                     s.replacements)
        typed = joined(prefix, text) if target.live_typing else text
        problem = target.write(typed)
        if problem:
            self.problem(problem)
            return
        self.last_message = text
        if how in ("send", "pause"):
            if s.check_unclear and sureness < UNCLEAR:
                self.show("problem", "Not sure I heard right, so not sent. Check it", text)
                self.say("unclear")
                self.say_text(text)
                return
            self.sent(target.send())
        else:
            self.show("idle", f"Left unsent. Say “{s.wake_name}, send it”")
            self.say("left")

    def transcribe(self, model, chunks: list[np.ndarray], beam_size: int) -> tuple[str, float]:
        """(the words, how sure: the average log-probability, 0 = certain)."""
        s = self.settings
        sound = np.concatenate(chunks).astype(np.float32) / 32768
        segments, _ = model.transcribe(
            sound, language=s.language, beam_size=beam_size, vad_filter=True,
            hotwords=", ".join(s.words) if s.words else None,
        )
        segments = list(segments)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        sureness = sum(seg.avg_logprob for seg in segments) / len(segments) if segments else 0.0
        return text, sureness

    def sent(self, problem: str) -> None:
        if problem:
            self.problem(problem)
        else:
            self.show("idle", "Sent")
            self.say("sent")

    # --- commands ------------------------------------------------------------------

    def command(self, name: str, arg: str, target, prefix: str) -> None:
        log.info("command: %s %s", name, arg)
        stop_answer()
        if name == "scratch":
            if target.live_typing:
                target.write("")
            self.show("idle", "Cleared")
            self.say("cleared")
            return
        if target.live_typing:
            target.write(prefix)  # put back what was there before
        if name == "send":
            self.sent(target.send())
        elif name == "quiet":
            self.show("idle", self.idle_text)
        elif name == "stop":
            problem = target.escape()
            if problem:
                self.problem(problem)
            else:
                self.show("idle", "Stopped")
                self.say("stopped")
        elif name == "voice off":
            paths.VOICE_OFF.touch()
            self.show("idle", "Spoken answers are off")
            self.say("voiceoff")
        elif name == "voice on":
            paths.VOICE_OFF.unlink(missing_ok=True)
            self.show("idle", "Spoken answers are on")
            self.say("voiceon")
        elif name == "help":
            ui_events.put(("help", "toggle"))
            self.show("idle", self.idle_text)
        elif name == "repeat":
            try:
                answer = paths.LAST_ANSWER.read_text(encoding="utf-8")
            except OSError:
                answer = ""
            if not answer.strip():
                self.problem("noanswer")
                return
            self.show("idle", "Repeating the answer")
            self.say_text(answer)
        elif name == "read back":
            text = prefix if target.can_read else getattr(target, "typed", "")
            if not text:
                self.problem("empty")
                return
            self.show("idle", "Reading your message back", text)
            self.say_text(text)
        elif name == "change":
            if not target.can_read:
                self.problem("notsupported")
                return
            wrong, right = arg.split("\t")
            new = change(prefix, wrong, right)
            if new is None:
                self.problem("notfound")
                return
            target.write(new)
            self.show("idle", f"Changed “{wrong}” to “{right}”")
            self.say("changed")
        elif name == "spell":
            problem = target.write(joined(prefix, arg) if target.live_typing else arg)
            if problem:
                self.problem(problem)
            else:
                self.show("idle", f"Typed “{arg}”")
                self.say("typed")
