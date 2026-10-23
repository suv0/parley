"""The answer reader's place in an answer: more, skip, go back, pause. Nothing is played here."""

import io
import json

from utter import settings as paths
from utter import speak_reply
from utter.speaker import Speaker
from utter.spoken import Spoken


def reader():
    paths.STATE.mkdir(parents=True, exist_ok=True)
    return Speaker(paths.Settings(), busy=lambda: False, speak=False)


def test_a_new_answer_reads_the_short_version_and_keeps_the_rest():
    sp = reader()
    sp.answer("The tests pass.", ["First detail.", "Second detail."])
    assert sp.parts[0] == "The tests pass."
    assert "more" in sp.parts[-1]  # it says there's more
    assert sp.rest == ["First detail.", "Second detail."]


def test_more_reads_the_rest_then_says_there_is_nothing_left():
    sp = reader()
    sp.answer("Short.", ["Rest one.", "Rest two."])
    sp.index = len(sp.parts)  # the short part has been read
    assert sp.more()
    assert sp.parts == ["Rest one.", "Rest two."] and sp.index == 0
    sp.index = len(sp.parts)
    assert not sp.more()


def test_more_after_waking_utter_carries_on_where_it_stopped():
    sp = reader()
    sp.answer("Short.", ["Rest one.", "Rest two."])
    assert sp.more()  # reading the rest
    sp.index = 1
    sp.interrupt()  # you said "Hey Claude"
    assert sp.paused
    assert sp.more()
    assert not sp.paused and sp.index == 1 and sp.parts == ["Rest one.", "Rest two."]


def test_skip_and_go_back_move_one_part():
    sp = reader()
    sp.say("One.")
    sp.parts, sp.index = ["One.", "Two.", "Three."], 1
    assert sp.skip() and sp.index == 2
    assert sp.back() and sp.index == 1
    sp.index = 3
    assert not sp.skip()


def test_repeat_reads_the_last_short_version_again():
    sp = reader()
    sp.answer("Said once.", [])
    sp.parts, sp.index = [], 0
    assert sp.repeat() and sp.parts == ["Said once."]


def test_quiet_from_outside_clears_what_was_left():
    from utter.voice import stop_answer

    sp = reader()
    sp.answer("Short.", ["Rest."])
    stop_answer()  # "quiet", or the tray
    assert sp.parts == []


def test_the_hook_hands_answers_to_utter_when_it_runs(monkeypatch):
    for old in paths.INBOX.glob("*.json") if paths.INBOX.exists() else []:
        old.unlink()
    monkeypatch.setattr(speak_reply, "utter_running", lambda: True)
    monkeypatch.setattr(speak_reply, "for_listening", lambda text, s: Spoken("Done.", ["More."], "claude"))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"last_assistant_message": "**Done.** More."})))
    speak_reply.main()
    found = list(paths.INBOX.glob("*.json"))
    assert len(found) == 1
    assert json.loads(found[0].read_text(encoding="utf-8")) == {"short": "Done.", "more": ["More."], "by": "claude"}
    found[0].unlink()


def test_the_hook_ignores_claudes_own_rewrite_run(monkeypatch):
    monkeypatch.setenv("UTTER_REWRITING", "1")
    monkeypatch.setattr(speak_reply, "for_listening", lambda *_: (_ for _ in ()).throw(AssertionError("read")))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"last_assistant_message": "Hello there."})))
    speak_reply.main()
