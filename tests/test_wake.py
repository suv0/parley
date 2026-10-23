"""The wake check's arithmetic. The recorded-speech wake bench is in test_listening.py."""

import numpy as np

from utter.wake import Surroundings, find, mentions


def sounds(*levels: float) -> Surroundings:
    around = Surroundings()
    for loud in levels:
        around.add(np.full(1600, int(loud * 32768), dtype=np.int16))
    return around


def test_a_phrase_with_quiet_around_it_was_said_alone():
    around = sounds(*[0.0] * 10, *[0.05] * 8, *[0.0] * 10)  # quiet, the phrase, quiet
    assert around.said_alone([{"word": "hey", "start": 1.0, "end": 1.3}, {"word": "claude", "start": 1.3, "end": 1.8}], floor=0.008)


def test_a_phrase_inside_other_speech_was_not():
    around = sounds(*[0.05] * 28)
    assert not around.said_alone([{"word": "hey", "start": 1.0, "end": 1.3}, {"word": "claude", "start": 1.3, "end": 1.8}], floor=0.008)


def test_quieter_sound_in_the_background_is_fine():
    around = sounds(*[0.01] * 10, *[0.06] * 8, *[0.01] * 10)  # a TV behind you, you louder
    assert around.said_alone([{"word": "hey", "start": 1.0, "end": 1.3}, {"word": "claude", "start": 1.3, "end": 1.8}], floor=0.008)


def test_speech_right_after_the_phrase_means_it_was_part_of_a_sentence():
    around = sounds(*[0.0] * 10, *[0.05] * 18)
    assert not around.said_alone([{"word": "hey", "start": 1.0, "end": 1.3}, {"word": "claude", "start": 1.3, "end": 1.8}], floor=0.008)


def test_utters_own_answer_mentioning_the_name_counts():
    phrases = ["hey claude", "hey cloud", "okay claude"]
    assert mentions("Ask Claude to check it.", phrases)
    assert mentions("The cloud build passed.", phrases)
    assert not mentions("The tests passed.", phrases)


def word(w, start):
    return {"word": w, "start": start, "end": start + 0.3, "conf": 1.0}


def test_the_wake_phrase_is_found_inside_a_longer_utterance():
    phrases = ["hey claude", "hey clawed", "okay claude"]
    heard = [word("[unk]", 0.0), word("hey", 0.5), word("clawed", 0.8), word("yeah", 1.4)]
    assert [w["word"] for w in find(heard, phrases)] == ["hey", "clawed"]
    assert [w["word"] for w in find([word("[unk]", 0), word("claude", 0.3)], phrases)] == ["[unk]", "claude"]
    assert find([word("hey", 0), word("[unk]", 0.3)], phrases) == []
