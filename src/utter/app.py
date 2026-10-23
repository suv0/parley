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
import re
import threading
import time

import numpy as np

from . import settings as paths
from .targets import Hands, clipboard_text, pc_locked, restore_clipboard
from .speaker import Speaker
from .voice import clip, cue, make_audio, play, remove_old_answers, speaking, stop_answer, stop_player
from .wake import AFTER, Surroundings, find, level, mentions
from .words import change, ends_with_send, joined, only_phantoms, parse, strip_send_phrase, tidy, without_repeats

log = logging.getLogger("utter")

RATE = 16000
BLOCK = 1600  # 0.1 s
LIVE_EVERY = 1.0  # seconds of audio between live updates
UNCLEAR = -0.85  # average log-probability below which Utter isn't sure it heard right
LOCK_PAUSE = 0.8  # seconds of quiet that end a piece of speech, so its words are locked in
LOCK_SHORTEST = 4.0  # a piece is at least this long, so short commands and phrases stay whole
LOCK_LONGEST = 10.0  # seconds of speech without a pause before the finished part is locked anyway
BEHIND = 10  # blocks waiting (1 s): live words skip an update to catch up
# Everyday words the wake recognizer may choose instead of a wake phrase, so speech that only
# sounds a bit like "Hey Claude" lands on one of these and wakes nothing.
# Nothing that sounds like the name itself: with noise behind you, "clyde" won over "claude".
DECOYS = ["hey", "okay", "hi", "hello", "yeah", "cool", "the"]

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
    "locked": "Your PC is locked. Unlock it, then try again.",
    "unclear": "I'm not sure I heard that right, so I didn't send it. Here's what I typed.",
    "changed": "Changed.",
    "notfound": "I couldn't find that in the box.",
    "notsupported": "That only works in the Claude app's message box.",
    "noanswer": "There's no answer to repeat yet.",
    "typed": "Typed.",
    "cancelled": "Cancelled.",
    "nottyped": "I wasn't sure I heard you, so I didn't type anything.",
    "nomore": "That's all of it.",
    "notreading": "I'm not reading anything right now.",
    "slower": "Okay, slower.",
    "faster": "Okay, faster.",
    "sleeping": "Going to sleep. Say {wake}, wake up, when you need me.",
    "awake": "I'm listening again.",
    "beepsoff": "Okay, no more beeps.",
    "beepson": "Beeps are back on.",
    "offline": "Okay, I'll use the offline voice.",
    "online": "Okay, I'll use the natural voice.",
    "notsent": "Okay, I didn't send it. It's still there.",
    "helpoffer": "If you're stuck, say {wake}, help.",
}
LONG_MESSAGE = 40  # words: longer messages are read back briefly before they're sent
# Whisper invents these from noise or music. On their own, they mean nobody spoke.
PHANTOMS = {
    "thank you", "thanks", "thank you very much", "thanks for watching", "thank you for watching",
    "see you next time", "well see you next time", "bye", "goodbye", "you", "subscribe",
    "please subscribe", "like and subscribe", "music", "applause", "so", "okay", "oh",
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
    "locked": "The PC is locked",
}


class Refiner:
    """Runs the accurate final pass on each locked piece of a message in the background."""

    def __init__(self, transcribe, chunks: list[np.ndarray]) -> None:
        self.transcribe = transcribe
        self.chunks = chunks  # the message's audio, growing as you talk
        self.locked_at = 0  # blocks before this are locked in
        self.jobs: queue.Queue = queue.Queue()
        self.results: list[tuple[str, float]] = []
        threading.Thread(target=self._run, daemon=True).start()

    def lock(self, upto: int) -> None:
        if upto > self.locked_at:
            self.results.append(("", 0.0))
            self.jobs.put((len(self.results) - 1, self.chunks[self.locked_at:upto]))
            self.locked_at = upto

    def close(self) -> None:
        self.jobs.put((None, None))

    def _run(self) -> None:
        while True:
            index, part = self.jobs.get()
            if index is None:
                return
            try:
                self.results[index] = self.transcribe(part)
            except Exception:
                log.exception("final pass failed")
            finally:
                self.jobs.task_done()

    def wait(self) -> list[tuple[str, float]]:
        self.jobs.join()
        return self.results


class Assistant:
    def __init__(self, settings: paths.Settings, hands=None, speak: bool = True) -> None:
        self.settings = settings
        self.hands = hands
        self.speak = speak  # False in tests: no beeps or spoken replies
        self.realtime = True  # False in tests, which feed recorded audio faster than real time
        self.idle_text = f"Say “{settings.wake_name}”" + (f" or press {settings.hotkey}" if settings.hotkey else "")
        self.audio: queue.Queue[np.ndarray] = queue.Queue()
        self.ears = threading.Event()  # set = keep what the mic hears
        self.hotkey = threading.Event()  # set when the shortcut is pressed
        self.speaker = Speaker(settings, busy=paths.LISTENING_FLAG.exists, speak=speak)
        self.awake_text = self.idle_text
        self.sleeping = False  # "go to sleep": only "Hey Claude, wake up" (or the shortcut) wakes it
        self.failures = 0  # problems in a row
        self.state = ("idle", self.idle_text)

    # --- status and sound ----------------------------------------------------------

    def show(self, state: str, text: str, live: str = "") -> None:
        """state: idle | listening | working | paused | problem"""
        log.info("status: %s | %s%s", state, text, f" | {self.private(live)}" if live else "")
        self.state = (state, text)
        ui_events.put(("status", f"{state}\t{text}\t{live}"))

    def private(self, words: str) -> str:
        """`words` for the log: the words themselves only when log_words is on."""
        return words if self.settings.log_words else f"<{len(words.split())} words>"

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
        if self.speak and text.strip():
            self.speaker.say(text)

    def say_now(self, text: str) -> None:
        """Says `text` and waits until it's said, like `say` but for words made up on the spot."""
        if not self.speak:
            return
        audio = None
        try:
            audio = make_audio(text, self.settings, paths.STATE / f"spoken-{time.time_ns()}")
            play(audio, wait=True)
        except Exception:
            log.exception("saying failed")
        finally:
            if audio is not None:
                audio.unlink(missing_ok=True)

    def beep(self, name: str) -> None:
        if self.speak and self.settings.cue_sounds:
            cue(name)

    def problem(self, name: str) -> None:
        name = name if name in SAYINGS else "failed"
        self.show("problem", STATUS.get(name, SAYINGS[name]))
        self.beep("error")
        self.say(name)
        self.failures += 1
        if self.failures == 2:  # the same trouble twice: point to help instead of repeating
            self.say("helpoffer")

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
        # One recognizer for the whole run, reset after each message. Making new ones with
        # word times on crashes Vosk 0.3.45 after a few dozen.
        self.wake = vosk.KaldiRecognizer(vosk.Model(str(paths.VOSK_MODEL)), RATE)
        self.wake.SetGrammar(json.dumps(s.wake_phrases + self.wake_ups() + DECOYS + ["[unk]"]))
        self.wake.SetWords(True)  # word times, to check the phrase was said on its own
        self.wake.SetPartialWords(True)  # and for words still being heard
        return True

    def wake_ups(self) -> list[str]:
        """"Hey Claude, wake up": wakes Utter from sleep."""
        return [f"{p} wake up" for p in self.settings.wake_phrases]

    def heard_wake(self, block: np.ndarray) -> str:
        """The wake phrase when this block completes one said to Utter, else ""."""
        # The recognizer's clock counts every sample it was given, resets included, so the
        # loudness history lives with the recognizer.
        around = getattr(self.wake, "utter_surroundings", None)
        if around is None:
            around = self.wake.utter_surroundings = Surroundings()
            around.judged = set()  # start times of phrases already decided
        around.add(block)
        phrases = self.settings.wake_phrases + self.wake_ups()  # the longer one wins when both fit
        if self.wake.AcceptWaveform(block.tobytes()):
            result = json.loads(self.wake.Result())
            words, text = find(result.get("result", []), phrases), result.get("text", "")
        else:
            # With a TV or other voices behind you the recognizer never hears the silence that
            # ends an utterance, so look at the words still being heard too.
            partial = json.loads(self.wake.PartialResult())
            words, text = find(partial.get("partial_result", []), phrases), partial.get("partial", "")
            if words and around.fed / RATE < words[-1]["end"] + AFTER[1]:
                return ""  # wait until the moment after the phrase can be checked
        if not words:
            return ""
        start = round(words[-1]["start"], 1)
        if start in around.judged:
            return ""
        around.judged.add(start)
        heard = " ".join(w["word"] for w in words)
        if not around.said_alone(words, self.settings.speaking_level):
            log.info("ignored %r in %s: as loud as the sound around it", heard, self.private(text))
            return ""
        if mentions(speaking(), self.settings.wake_phrases):
            log.info("ignored %r: Utter's own answer is saying it", heard)
            return ""
        if self.sleeping and not heard.endswith("wake up"):
            log.info("ignored %r: asleep", heard)
            return ""
        return heard

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
                self.idle_text = self.awake_text = f"Say “{s.wake_name}” (shortcut {s.hotkey} {taken})"
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
                if paused.is_set():
                    continue
                woke = self.heard_wake(block)
                if not woke:
                    continue
            if paused.is_set():
                continue
            log.info("wake: %s", woke)
            if woke.endswith("wake up") or (self.sleeping and woke == "shortcut"):
                self.sleeping = False
                self.idle_text = self.awake_text
                self.show("idle", self.idle_text)
                self.say("awake")
                if woke != "shortcut":
                    self.wake.Reset()
                    continue
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
        if self.realtime and pc_locked():
            self.problem("locked")  # Windows lets nothing type into the lock screen
            return
        self.speaker.interrupt()  # keeps its place, so "more" carries on
        stop_player()  # an answer the hook read itself, while Utter wasn't running
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
            if getattr(self, "refiner", None) is not None:  # the message ended without a final pass
                self.refiner.close()
                self.refiner = None
            restore_clipboard(saved_clipboard)
            paths.LISTENING_FLAG.unlink(missing_ok=True)

    def hear(self, target, prefix: str, listening: str) -> tuple[str, list[np.ndarray], str]:
        """Collects the message. How it ended: send | pause | leave | command | nothing.

        Finished speech is locked in and never transcribed again: live updates only look at the
        unfinished tail, so they cost the same after three minutes as after three seconds. Each
        locked piece gets the accurate final pass in the background while you keep talking.
        """
        s = self.settings
        chunks: list[np.ndarray] = []
        self.refiner = refiner = Refiner(lambda part: self.transcribe(self.final_model, part, beam_size=5), chunks)
        heard_at = None  # seconds of audio at the last loud block
        next_update = LIVE_EVERY
        live = locked = tail = ""
        fresh = False  # loud audio the live words don't include yet
        started = last_audio = time.time()
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
                fresh = True
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
                behind = self.realtime and self.audio.qsize() > BEHIND
                if fresh and not behind:  # when behind, skip this update rather than fall further back
                    fresh = False
                    segments = self.segments(self.live_model, chunks[refiner.locked_at:], beam_size=1)
                    tail = " ".join(seg.text.strip() for seg in segments).strip()
                    if (len(chunks) - refiner.locked_at) * BLOCK / RATE > LOCK_LONGEST and len(segments) > 1:
                        # A long stretch without a pause: lock everything before the last segment.
                        cut = refiner.locked_at + int(segments[-1].start * RATE / BLOCK)
                        locked = joined(locked, " ".join(seg.text.strip() for seg in segments[:-1]))
                        refiner.lock(cut)
                        tail = segments[-1].text.strip()
                long_enough = (len(chunks) - refiner.locked_at) * BLOCK / RATE >= LOCK_SHORTEST
                if tail and not fresh and quiet >= LOCK_PAUSE and long_enough:  # a pause ends a piece
                    locked = joined(locked, tail)
                    refiner.lock(len(chunks))
                    tail = ""
                words = joined(locked, tail)
                if words and words != live:
                    live = words
                    if target.live_typing and not parse(live, s.wake_phrases)[0]:
                        target.write(joined(prefix, tidy(live, s.remove_fillers, s.replacements)))
                    self.show("listening", listening, live)
                if ends_with_send(live, s.send_phrases):
                    return "send", chunks, live
            if self.realtime and time.time() - started > s.max_message_seconds + 30:
                return "leave", chunks, live
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
            self.cancelled(target, prefix, "Nothing heard, so back to waiting")
            return
        self.show("working", "Getting your words right")
        final, sureness = self.final_words(chunks)
        final = final or live
        log.info("final: %s (%s, sureness %.2f)", self.private(final), how, sureness)
        if only_phantoms(final, PHANTOMS):
            log.info("only noise: %s", self.private(final))
            self.cancelled(target, prefix, "Only noise heard, so nothing was typed")
            return
        command, arg = parse(final, s.wake_phrases)
        if not command and how == "command":
            command, arg = parse(live, s.wake_phrases)
        if command and command != "literal":
            self.command(command, arg, target, prefix)
            return
        text = arg if command == "literal" else tidy(strip_send_phrase(final, s.send_phrases), s.remove_fillers,
                                                     s.replacements)
        if not target.live_typing and how == "leave" and sureness < UNCLEAR:
            # Another app can't be checked or cleared by voice, so don't paste words that may be noise.
            self.show("problem", "Not typed: I wasn't sure I heard you", text)
            self.say("nottyped")
            return
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
            if len(text.split()) >= LONG_MESSAGE and self.objection(text):
                self.show("idle", f"Left unsent. Say “{s.wake_name}, send it”")
                self.say("notsent")
                return
            self.sent(target.send())
        else:
            self.show("idle", f"Left unsent. Say “{s.wake_name}, send it”")
            self.say("left")

    def cancelled(self, target, prefix: str, why: str) -> None:
        """Back to waiting without a fuss: put the box back as it was, and a soft tone."""
        if target.live_typing:
            target.write(prefix)
        self.show("idle", why)
        if self.settings.cue_sounds:
            self.beep("cancel")
        else:
            self.say("cancelled")

    def final_words(self, chunks: list[np.ndarray]) -> tuple[str, float]:
        """The accurate transcript: the locked pieces (mostly done already) plus the tail."""
        refiner, self.refiner = getattr(self, "refiner", None), None
        if refiner is None or refiner.chunks is not chunks:
            return self.transcribe(self.final_model, chunks, beam_size=5)
        refiner.lock(len(chunks))
        parts = [part for part in refiner.wait() if part[0]]
        refiner.close()
        if not parts:
            return "", 0.0
        return " ".join(text for text, _ in parts), sum(sure for _, sure in parts) / len(parts)

    def segments(self, model, chunks: list[np.ndarray], beam_size: int) -> list:
        """What the model heard in `chunks`, one segment per phrase."""
        if not chunks:
            return []
        s = self.settings
        sound = np.concatenate(chunks).astype(np.float32) / 32768
        found, _ = model.transcribe(
            sound, language=s.language, beam_size=beam_size, vad_filter=True,
            hotwords=", ".join(s.words) if s.words else None,
        )
        # Drop what Whisper invents from noise: segments it thinks hold no speech and isn't sure
        # of, and looping repeats (a high compression ratio).
        return [seg for seg in found
                if not (seg.no_speech_prob > 0.6 and seg.avg_logprob < -0.5) and seg.compression_ratio < 2.4]

    def transcribe(self, model, chunks: list[np.ndarray], beam_size: int) -> tuple[str, float]:
        """(the words, how sure: the average log-probability, 0 = certain)."""
        segments = self.segments(model, chunks, beam_size)
        text = without_repeats(" ".join(seg.text.strip() for seg in segments).strip())
        sureness = sum(seg.avg_logprob for seg in segments) / len(segments) if segments else 0.0
        return text, sureness

    def objection(self, text: str, seconds: float = 2.5) -> bool:
        """Reads the start of a long message back, then listens a moment for "wait"."""
        if not self.speak:
            return False
        self.say_now("Sending: " + " ".join(text.split()[:8]) + "...")
        self.drain()
        self.ears.set()
        chunks, end = [], time.time() + seconds
        while time.time() < end:
            try:
                chunks.append(self.audio.get(timeout=0.2))
            except queue.Empty:
                pass
        self.ears.clear()
        if not any(level(c) > self.settings.speaking_level for c in chunks):
            return False
        heard, _ = self.transcribe(self.live_model, chunks, beam_size=1)
        return bool(re.search(r"\b(wait|stop|no|don'?t|cancel|hold)\b", heard.lower()))

    def sent(self, problem: str) -> None:
        if problem:
            self.problem(problem)
        else:
            self.failures = 0
            self.speaker.last_sent = time.time()
            self.show("idle", "Sent")
            self.say("sent")
            self.beep("thinking")  # Claude is working on it

    # --- commands ------------------------------------------------------------------

    def command(self, name: str, arg: str, target, prefix: str) -> None:
        log.info("command: %s %s", name, arg)
        if target.live_typing and name not in ("scratch", "cancel"):
            target.write(prefix)  # put back what was there before
        if self.answer_command(name):
            return
        stop_answer()
        if name == "scratch":
            if target.live_typing:
                target.write("")
            self.show("idle", "Cleared")
            self.say("cleared")
            return
        if name == "cancel":
            self.cancelled(target, prefix, "Cancelled")
            return
        if name == "send":
            self.sent(target.send())
        elif name == "quiet":
            self.show("idle", self.idle_text)
        elif name == "sleep":
            self.sleeping = True
            self.idle_text = f"Asleep. Say “{self.settings.wake_name}, wake up”"
            self.show("paused", self.idle_text)
            self.say("sleeping")
        elif name in ("beeps off", "beeps on"):
            self.change_setting("cue_sounds", name == "beeps on")
            self.show("idle", "Beeps are " + ("on" if name == "beeps on" else "off"))
            self.say("beepson" if name == "beeps on" else "beepsoff")
        elif name in ("offline voice", "online voice"):
            self.change_setting("voice_engine", "windows" if name == "offline voice" else "edge")
            self.show("idle", "Offline voice" if name == "offline voice" else "Natural voice")
            self.say("offline" if name == "offline voice" else "online")
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

    def answer_command(self, name: str) -> bool:
        """Commands about the answer being read, and about Utter. True when `name` was one."""
        sp = self.speaker
        if name == "more":
            if sp.more():
                self.show("idle", "Reading the rest")
            else:
                self.say("nomore")
        elif name in ("skip", "back", "pause"):
            if getattr(sp, name)():
                self.show("idle", {"skip": "Skipped", "back": "Going back", "pause": "Paused. Say “more” to go on"}[name])
            else:
                self.say("notreading")
        elif name == "repeat":
            if sp.repeat():
                self.show("idle", "Repeating the answer")
            else:
                self.problem("noanswer")
        elif name in ("slower", "faster"):
            rate = max(-50, min(50, self.settings.speaking_rate + (-15 if name == "slower" else 15)))
            self.change_setting("speaking_rate", rate)
            self.show("idle", f"Speaking speed {rate:+d}%")
            self.say(name)
            sp.more()  # carry on reading, at the new speed
        elif name == "status":
            self.say_now(self.status_words())
        elif name == "help":
            ui_events.put(("help", "toggle"))
            self.say_now(self.help_words())
        else:
            return False
        return True

    def change_setting(self, name: str, value) -> None:
        """Changes a setting now and in config.toml, so it stays after a restart."""
        setattr(self.settings, name, value)
        try:
            paths.save(name, value)
        except OSError:
            log.exception("couldn't save %s", name)

    def status_words(self) -> str:
        wake = self.settings.wake_name
        if self.sleeping:
            return f"I'm asleep. Say {wake}, wake up, when you need me."
        parts = ["I'm here and listening for you."]
        if paths.VOICE_OFF.exists():
            parts.append("Spoken answers are off.")
        if self.speaker.remaining():
            parts.append(f"There's more of the last answer. Say {wake}, more.")
        elif time.time() - self.speaker.last_sent < 120:
            parts.append("Claude may still be working on your last message.")
        return " ".join(parts)

    def help_words(self) -> str:
        """The few commands that make sense right now, spoken."""
        wake, send = self.settings.wake_name, (self.settings.send_phrases or ["send it"])[0]
        if self.speaker.remaining():
            return (f"While I read an answer, say {wake}, then: more, skip, go back, pause, slower, "
                    f"faster, or quiet.")
        return (f"Say {wake}, then your message, and end with {send}. You can also say {wake}, then: "
                f"read it back, scratch that, repeat that, more, cancel, or what's happening.")
