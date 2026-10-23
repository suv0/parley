"""Utter from wake phrase to sent message, with recorded speech instead of a microphone.

The speech is made with the Edge voice, so these tests need the internet and the installed
speech models (install.ps1). Without them they are skipped.
"""

from __future__ import annotations

import os

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("faster_whisper")
pytest.importorskip("vosk")
pytest.importorskip("edge_tts")

from utter import app as app_module  # noqa: E402
from utter import settings as paths  # noqa: E402
from utter.app import BLOCK, RATE, Assistant  # noqa: E402

if not os.environ.get("UTTER_MODELS") or not paths.VOSK_MODEL.exists():
    pytest.skip("speech models not installed", allow_module_level=True)

SPEECH_CACHE: dict[tuple[str, str], np.ndarray] = {}


def speech(text: str, voice: str = "en-US-AndrewMultilingualNeural") -> np.ndarray:
    """`text` spoken by an Edge voice, as 16 kHz 16-bit samples."""
    if (text, voice) not in SPEECH_CACHE:
        import asyncio
        import tempfile

        import av
        import edge_tts

        out = os.path.join(tempfile.mkdtemp(), "speech.mp3")
        asyncio.run(edge_tts.Communicate(text, voice).save(out))
        resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
        parts = []
        with av.open(out) as container:
            for frame in container.decode(audio=0):
                parts += [f.to_ndarray().reshape(-1) for f in resampler.resample(frame)]
        parts += [f.to_ndarray().reshape(-1) for f in resampler.resample(None)]
        SPEECH_CACHE[text, voice] = np.concatenate(parts).astype(np.int16)
    return SPEECH_CACHE[text, voice]


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * RATE), dtype=np.int16)


class FakeTarget:
    """Stands in for the Claude box (live typing, readable) or another app (paste once)."""

    def __init__(self, live: bool, text: str = "") -> None:
        self.live_typing = self.can_read = live
        self.name = "Claude app" if live else "Notepad"
        self.text = text
        self.writes: list[str] = []
        self.sent = 0
        self.escaped = 0
        self.typed = ""

    def read(self):
        return "", self.text if self.live_typing else ""

    def write(self, text: str) -> str:
        self.writes.append(text)
        if self.live_typing:
            self.text = text
        elif text:
            self.text += text
            self.typed = text
        return ""

    def send(self) -> str:
        if not self.text:
            return "empty"
        self.sent += 1
        return ""

    def escape(self) -> str:
        self.escaped += 1
        return ""


class FakeHands:
    def __init__(self, target: FakeTarget) -> None:
        self.target = target

    def pick(self, _where: str) -> FakeTarget:
        return self.target


@pytest.fixture(scope="module")
def models():
    a = Assistant(paths.Settings(), speak=False)
    assert a.load_models()
    return a.live_model, a.final_model, a.wake


def run(models, target: FakeTarget, *sounds: np.ndarray, **settings) -> Assistant:
    a = Assistant(paths.Settings(**settings), hands=FakeHands(target), speak=False)
    a.realtime = False
    a.live_model, a.final_model, a.wake = models
    a.wake.Reset()
    feed(a, *sounds)
    a.listen(until_empty=True)
    return a


def feed(a: Assistant, *sounds: np.ndarray) -> None:
    audio = np.concatenate([silence(0.5), *sounds])
    for start in range(0, len(audio) - BLOCK + 1, BLOCK):
        a.audio.put(audio[start:start + BLOCK])


def statuses() -> list[str]:
    out = []
    while not app_module.ui_events.empty():
        kind, text = app_module.ui_events.get_nowait()
        if kind == "status":
            out.append(text.split("\t")[1])
    return out


def wake():
    return speech("Hey Claude."), silence(1.0)


def test_a_message_ending_in_send_it_is_typed_live_and_sent(models):
    box = FakeTarget(live=True)
    run(models, box, *wake(), speech("Fix the login page on the website. Send it."), silence(3))
    assert box.sent == 1
    assert box.text.lower().startswith("fix the login page on the website")
    assert "send it" not in box.text.lower()
    assert len(box.writes) >= 2  # live words, then the final text


def test_quiet_leaves_the_message_unsent(models):
    box = FakeTarget(live=True)
    run(models, box, *wake(), speech("Check the failing tests in the payment module."), silence(16))
    assert box.sent == 0
    assert "payment module" in box.text.lower()


def test_a_pause_sends_in_pause_mode(models):
    box = FakeTarget(live=True)
    run(models, box, *wake(), speech("Please run the unit tests."), silence(3), send_mode="pause")
    assert box.sent == 1
    assert "unit tests" in box.text.lower()


def test_other_apps_get_the_words_once_at_the_end(models):
    notepad = FakeTarget(live=False)
    run(models, notepad, *wake(), speech("Write a short poem about rain. Send it."), silence(3))
    assert len(notepad.writes) == 1
    assert "poem about rain" in notepad.text.lower()
    assert notepad.sent == 1


def test_scratch_that_clears_the_box(models):
    box = FakeTarget(live=True, text="Some old text")
    run(models, box, *wake(), speech("Scratch that."), silence(3))
    assert box.text == ""
    assert box.sent == 0


def test_stop_presses_escape_and_keeps_the_box(models):
    box = FakeTarget(live=True, text="Draft")
    run(models, box, *wake(), speech("Stop."), silence(3))
    assert box.escaped == 1
    assert box.text == "Draft"


def test_type_stop_types_the_word(models):
    box = FakeTarget(live=True)
    run(models, box, *wake(), speech("Type stop."), silence(16))
    assert box.escaped == 0
    assert box.text.lower().strip(".") == "stop"


def test_change_fixes_a_word_in_the_box(models):
    box = FakeTarget(live=True, text="Deploy the app to staging today")
    run(models, box, *wake(), speech("Change staging to production."), silence(3))
    assert box.text == "Deploy the app to production today"


def test_spell_types_letters(models):
    box = FakeTarget(live=True, text="Repo name:")
    run(models, box, *wake(), speech("Spell kilo, uniform, bravo, echo."), silence(3))
    assert box.text.lower() == "repo name: kube"


def test_read_it_back_and_repeat_need_no_typing(models):
    box = FakeTarget(live=True, text="Hello there")
    statuses()
    run(models, box, *wake(), speech("Read it back."), silence(3))
    assert "Reading your message back" in statuses()
    assert box.text == "Hello there"


def test_replacements_fix_words_it_gets_wrong(models):
    box = FakeTarget(live=True)
    run(models, box, *wake(), speech("Open the payment page. Send it."), silence(3),
        replacements={"payment page": "PaymentPage.tsx"})
    assert "PaymentPage.tsx" in box.text


def test_silence_after_waking_types_nothing(models):
    box = FakeTarget(live=True, text="Keep me")
    run(models, box, *wake(), silence(9))
    assert box.text == "Keep me"
    assert box.sent == 0


def test_without_the_wake_phrase_nothing_happens(models):
    box = FakeTarget(live=True)
    run(models, box, speech("Fix the login page. Send it."), silence(3))
    assert box.writes == [] and box.sent == 0


def test_an_unclear_message_is_typed_but_not_sent(models, monkeypatch):
    box = FakeTarget(live=True)
    a = Assistant(paths.Settings(), hands=FakeHands(box), speak=False)
    a.final_model = None
    monkeypatch.setattr(a, "transcribe", lambda *_args, **_kw: ("Mumble the grumble", -1.4))
    a.finish(box, "", "send", [silence(1)], "Mumble the grumble")
    assert box.text == "Mumble the grumble"
    assert box.sent == 0


LONG_MESSAGE = (
    "I want to change how the settings page works. Right now every change saves at once, and people "
    "lose work when they make a mistake. Add a save button at the bottom of the page. Keep the old values "
    "until the person presses it. Show a short message after saving, so they know it worked. "
    "If they leave the page with changes that are not saved, ask them first. "
    "The colour settings should show a preview before they are saved. "
    "Please also check the tests for the settings page and add new ones for the save button. "
    "When you are done, tell me which files changed and anything you were not sure about. "
    "One more thing. The page is slow on old laptops, so look at why it loads every setting twice. "
    "Fix that if it is simple, and leave a note if it is not. Send it."
)


def test_a_long_message_never_re_transcribes_what_is_already_settled(models):
    """The typing-lag fix: live updates only look at the unfinished tail, however long you talk."""
    box = FakeTarget(live=True)
    a = Assistant(paths.Settings(), hands=FakeHands(box), speak=False)
    a.realtime = False
    a.live_model, a.final_model, a.wake = models
    a.wake.Reset()
    longest = []
    segments = a.segments

    def measured(model, chunks, beam_size):
        if model is a.live_model:
            longest.append(len(chunks) * BLOCK / RATE)
        return segments(model, chunks, beam_size)

    a.segments = measured
    sentences = [speech(s.strip() + ".") for s in LONG_MESSAGE.split(".") if s.strip()]
    spoken = []
    for sound in sentences:
        spoken += [sound, silence(0.8)]
    feed(a, *wake(), *spoken, silence(3))
    a.listen(until_empty=True)

    total = sum(len(s) for s in sentences) / RATE
    assert total > 40  # a long message
    assert max(longest) < 16  # the live model never sees more than the unfinished tail
    assert box.sent == 1
    text = box.text.lower()
    assert "save button" in text and "loads every setting twice" in text
    assert "send it" not in text


# --- the wake bench: real wakes wake it, the same words in a film or a video don't -----------

VOICES = ["en-US-AndrewMultilingualNeural", "en-US-JennyNeural", "en-GB-SoniaNeural", "en-IN-PrabhatNeural",
          "en-US-GuyNeural", "en-AU-WilliamMultilingualNeural"]


def trimmed(sound: np.ndarray) -> np.ndarray:
    """Without the half second of silence the voice puts at each end, as in real dialogue."""
    loud = np.flatnonzero(np.abs(sound) > 300)
    return sound[loud[0]:loud[-1] + 1] if len(loud) else sound


def wakes(models, *sounds: np.ndarray) -> int:
    a = Assistant(paths.Settings(), hands=FakeHands(FakeTarget(live=True)), speak=False)
    a.realtime = False
    a.live_model, a.final_model, a.wake = models
    a.wake.Reset()
    woke = []
    a.one_message = lambda: woke.append(1)
    feed(a, *sounds)
    a.listen(until_empty=True)
    return len(woke)


def test_hey_claude_said_on_its_own_wakes_it_in_most_voices(models):
    woke = sum(wakes(models, silence(1), speech("Hey Claude.", v), silence(1.5)) > 0 for v in VOICES)
    assert woke >= len(VOICES) - 1


def test_wake_phrases_inside_dialogue_do_not_wake_it(models):
    lines = [("So what's your name?", "Okay Claude.", "Take me inside."),
             ("We need to leave now.", "Hey cloud.", "Is the family okay?"),
             ("Look at the sky.", "Hi Claude.", "It's going to rain again.")]
    woke = 0
    for before, phrase, after in lines:
        for v in VOICES[:3]:
            woke += wakes(models, trimmed(speech(before, v)), silence(0.25), trimmed(speech(phrase, v)),
                          silence(0.25), trimmed(speech(after, v)), silence(1.5))
    assert woke == 0


def test_hey_claude_over_a_quieter_tv_still_wakes_it(models):
    tv = np.concatenate([speech("So what's your name? Maria. Take me inside, is the family okay?", "en-US-AriaNeural")] * 2)
    you = np.concatenate([silence(1.5), speech("Hey Claude.", "en-US-JennyNeural"), silence(1.5)])
    room = tv[: len(you)].astype(np.int32) // 6 + you
    assert wakes(models, room.astype(np.int16)) == 1


def test_noise_that_whisper_turns_into_thank_you_types_nothing(models, monkeypatch):
    box = FakeTarget(live=True, text="Keep me")
    a = Assistant(paths.Settings(), hands=FakeHands(box), speak=False)
    a.final_model = None
    monkeypatch.setattr(a, "final_words", lambda _chunks: ("Thank you. Thank you.", -0.9))
    a.finish(box, "Keep me", "leave", [silence(1)], "Thank you.")
    assert box.text == "Keep me"


def test_never_mind_cancels_and_types_nothing(models):
    box = FakeTarget(live=True, text="Draft")
    run(models, box, *wake(), speech("Never mind."), silence(3))
    assert box.text == "Draft" and box.sent == 0 and box.escaped == 0


def test_unsure_words_are_not_pasted_into_another_app(models, monkeypatch):
    notepad = FakeTarget(live=False)
    a = Assistant(paths.Settings(), hands=FakeHands(notepad), speak=False)
    a.final_model = None
    monkeypatch.setattr(a, "final_words", lambda _chunks: ("Maria take me inside", -1.3))
    a.finish(notepad, "", "leave", [silence(1)], "Maria take me inside")
    assert notepad.writes == []
