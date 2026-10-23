import os
import time

import pytest

from utter import settings as paths
from utter import voice


class FakePlayer:
    pid = 4242


@pytest.fixture
def no_processes(monkeypatch):
    """Nothing is really played or killed; the calls are recorded instead."""
    killed = []
    monkeypatch.setattr(voice.subprocess, "run", lambda args, **_: killed.append(args))
    monkeypatch.setattr(voice, "play", lambda path, wait=True, delete_after=False: FakePlayer())
    paths.STATE.mkdir(parents=True, exist_ok=True)
    paths.PLAYER_PID.unlink(missing_ok=True)
    yield killed
    paths.PLAYER_PID.unlink(missing_ok=True)


def answer(name: str):
    path = paths.STATE / name
    path.write_bytes(b"audio")
    return path


def test_stopping_an_answer_deletes_its_audio(no_processes):
    audio = answer("answer-1.mp3")
    voice.play_as_answer(audio, delete_after=True)
    voice.stop_answer()
    assert not audio.exists()
    assert no_processes == [["taskkill", "/PID", "4242", "/T", "/F"]]


def test_the_next_answer_deletes_the_one_it_interrupts_but_not_itself(no_processes):
    first, second = answer("answer-1.mp3"), answer("answer-2.mp3")
    voice.play_as_answer(first, delete_after=True)
    voice.play_as_answer(second, delete_after=True)
    assert not first.exists()
    assert second.exists()


def test_stopping_keeps_audio_that_is_not_a_one_off(no_processes):
    kept = answer("clip.mp3")
    voice.play_as_answer(kept)
    voice.stop_answer()
    assert kept.exists()
    kept.unlink()


def test_an_old_player_file_with_only_a_pid_still_stops(no_processes):
    paths.PLAYER_PID.write_text("4242")
    voice.stop_answer()
    assert no_processes == [["taskkill", "/PID", "4242", "/T", "/F"]]
    assert not paths.PLAYER_PID.exists()


def test_startup_clears_old_leftover_answers_only():
    paths.CLIPS.mkdir(parents=True, exist_ok=True)
    hour_ago = time.time() - 2 * 3600
    old = [answer("answer-7.mp3"), answer("answer-8.wav"), answer("spoken-9.mp3")]
    for path in old:
        os.utime(path, (hour_ago, hour_ago))
    fresh = answer("answer-10.mp3")
    cached = paths.CLIPS / "abc.mp3"
    cached.write_bytes(b"audio")
    os.utime(cached, (hour_ago, hour_ago))

    voice.remove_old_answers()

    assert not any(path.exists() for path in old)
    assert fresh.exists() and cached.exists()
    fresh.unlink()
    cached.unlink()
