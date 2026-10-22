"""The listening loop: wait for the wake phrase, then type what you say into Claude.

1. "Hey Claude" -> "Yes?"
2. You talk; the words appear live in the Claude message box.
3. "...send it" sends. 15 seconds of quiet leaves the words in the box, unsent.
A bare command after the wake phrase ("scratch that", "quiet", "stop", ...) runs instead.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time

import numpy as np

from . import settings as paths
from .claude_box import ClaudeBox, clipboard_text, restore_clipboard
from .voice import clip, play, stop_answer
from .words import command_in, ends_with_send, joined, strip_send_phrase

log = logging.getLogger("parley")

RATE = 16000
BLOCK = 1600  # 0.1 s
LIVE_EVERY = 1.0  # seconds between live updates of the box

paused = threading.Event()
stopping = threading.Event()
ui_events: queue.Queue[tuple[str, str]] = queue.Queue()  # (kind, text) for the strip and tray

SAYINGS = {
    "yes": "Yes?",
    "sent": "Sent.",
    "left": "I left it in the box. Say {wake}, send it, when you're ready.",
    "nothing": "I didn't hear anything.",
    "cleared": "Cleared.",
    "empty": "The box is empty, so there's nothing to send.",
    "nowindow": "I can't find the Claude app. Open it, then try again.",
    "noclick": "Click the Claude message box once, then try again.",
    "failed": "Something went wrong typing that.",
    "stopped": "Stopped.",
    "voiceoff": "Okay, I'll stop reading my answers. Say voice on to bring them back.",
    "voiceon": "Voice is back on.",
    "nomic": "I can't use the microphone. Check the Windows microphone privacy setting.",
}
STATUS = {
    "nowindow": "Can't find the Claude app",
    "noclick": "Click a Claude message box once",
    "empty": "The box is empty",
    "failed": "Couldn't type that",
}


class Assistant:
    def __init__(self, settings: paths.Settings) -> None:
        self.settings = settings
        self.idle_text = f"Say “{settings.wake_name}”"
        self.audio: queue.Queue[np.ndarray] = queue.Queue()
        self.ears = threading.Event()  # set = keep what the mic hears
        self.box: ClaudeBox | None = None

    # --- status and speech ---------------------------------------------------------

    def show(self, state: str, text: str, live: str = "") -> None:
        """state: idle | listening | working | paused | problem"""
        log.info("status: %s | %s", state, text)
        ui_events.put(("status", f"{state}\t{text}\t{live}"))

    def say(self, key: str, wait: bool = True) -> None:
        try:
            text = SAYINGS[key].format(wake=self.settings.wake_name)
            play(clip(text, self.settings.voice), wait=wait)
        except Exception:
            log.exception("say failed")

    def problem(self, name: str) -> None:
        name = name if name in SAYINGS else "failed"
        self.show("problem", STATUS.get(name, SAYINGS[name]))
        self.say(name)

    # --- start ---------------------------------------------------------------------

    def run(self) -> None:
        import sounddevice as sd
        import vosk
        from faster_whisper import WhisperModel

        s = self.settings
        self.show("working", "Starting up")
        vosk.SetLogLevel(-1)
        have = lambda name: any(paths.WHISPER_MODELS.glob(f"models--*faster-whisper-{name}"))  # noqa: E731
        if not paths.VOSK_MODEL.exists() or not have(s.live_model) or not have(s.final_model):
            self.show("problem", "Models missing. Run install.ps1 again")
            return
        load = lambda name: WhisperModel(  # noqa: E731
            name, device="cpu", compute_type="int8", download_root=str(paths.WHISPER_MODELS), local_files_only=True
        )
        self.live_model, self.final_model = load(s.live_model), load(s.final_model)
        self.wake = vosk.KaldiRecognizer(
            vosk.Model(str(paths.VOSK_MODEL)), RATE, json.dumps(s.wake_phrases + ["[unk]"])
        )
        for key in SAYINGS:  # make every spoken reply once, so none waits on the network later
            try:
                clip(SAYINGS[key].format(wake=s.wake_name), s.voice)
            except Exception:
                log.exception("could not make the %s clip (offline?)", key)
        self.box = ClaudeBox(stopping)
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

    def listen(self) -> None:
        while not stopping.is_set():
            try:
                block = self.audio.get(timeout=0.5)
            except queue.Empty:
                continue
            if paused.is_set() or not self.wake.AcceptWaveform(block.tobytes()):
                continue
            heard = json.loads(self.wake.Result()).get("text", "")
            if heard not in self.settings.wake_phrases:
                continue
            log.info("wake: %s", heard)
            try:
                self.one_message()
            except Exception:
                log.exception("message failed")
                self.show("problem", "Something went wrong. Try again")
            self.wake.Reset()
            self.drain()
            self.ears.set()
            if not paused.is_set():
                ui_events.put(("idle-later", ""))

    def drain(self) -> None:
        while not self.audio.empty():
            self.audio.get_nowait()

    # --- one message ---------------------------------------------------------------

    def one_message(self) -> None:
        s, box = self.settings, self.box
        stop_answer()
        paths.LISTENING_FLAG.write_text(str(time.time()))
        saved_clipboard = clipboard_text()
        try:
            self.ears.clear()
            self.say("yes")
            problem, prefix = box.read()
            if problem:
                self.problem(problem)
                return
            listening = f"Listening. Say “{s.send_phrases[0]}” when you’re done" if s.send_phrases else "Listening"
            self.show("listening", listening)
            self.drain()
            self.ears.set()

            chunks: list[np.ndarray] = []
            started = time.time()
            heard_at = None
            last_update = 0.0
            live = ""
            how = ""  # send | leave | command | nothing
            while True:
                try:
                    block = self.audio.get(timeout=0.5)
                    chunks.append(block)
                    if float(np.sqrt(np.mean((block.astype(np.float32) / 32768) ** 2))) > s.speaking_level:
                        heard_at = time.time()
                except queue.Empty:
                    pass
                now = time.time()
                if heard_at is None:
                    if now - started > s.nothing_heard_seconds:
                        how = "nothing"
                        break
                    continue
                quiet = now - heard_at
                if now - last_update >= LIVE_EVERY:
                    last_update = now
                    fresh = self.transcribe(self.live_model, chunks, beam_size=1)
                    if fresh and fresh != live:
                        live = fresh
                        if not command_in(live, s.wake_phrases):
                            box.write(joined(prefix, live))
                        self.show("listening", listening, live)
                    if ends_with_send(live, s.send_phrases):
                        how = "send"
                        break
                if live and command_in(live, s.wake_phrases) and quiet >= s.command_pause_seconds:
                    how = "command"
                    break
                if quiet >= s.quiet_seconds or now - started > s.max_message_seconds:
                    how = "leave"
                    break
            self.ears.clear()

            if how == "nothing":
                box.write(prefix)
                self.show("problem", "I didn't hear anything")
                self.say("nothing")
                return

            self.show("working", "Getting your words right")
            final = self.transcribe(self.final_model, chunks, beam_size=5) or live
            log.info("final: %r (%s)", final, how)
            command = command_in(final, s.wake_phrases) or (command_in(live, s.wake_phrases) if how == "command" else "")
            if command:
                self.command(command, prefix)
                return
            problem = box.write(joined(prefix, strip_send_phrase(final, s.send_phrases)))
            if problem:
                self.problem(problem)
            elif how == "send":
                self.sent(box.send())
            else:
                self.show("idle", f"Left in the box. Say “{s.wake_name}, send it”")
                self.say("left")
        finally:
            restore_clipboard(saved_clipboard)
            paths.LISTENING_FLAG.unlink(missing_ok=True)

    def transcribe(self, model, chunks: list[np.ndarray], beam_size: int) -> str:
        sound = np.concatenate(chunks).astype(np.float32) / 32768
        segments, _ = model.transcribe(sound, language="en", beam_size=beam_size, vad_filter=True)
        return " ".join(seg.text.strip() for seg in segments).strip()

    def sent(self, problem: str) -> None:
        if problem:
            self.problem(problem)
        else:
            self.show("idle", "Sent")
            self.say("sent")

    def command(self, name: str, prefix: str) -> None:
        log.info("command: %s", name)
        box = self.box
        stop_answer()
        if name == "scratch":
            box.write("")
            self.show("idle", "Cleared the box")
            self.say("cleared")
            return
        box.write(prefix)  # put back what was there before
        if name == "send":
            self.sent(box.send())
        elif name == "quiet":
            self.show("idle", self.idle_text)
        elif name == "stop":
            problem = box.escape()
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
