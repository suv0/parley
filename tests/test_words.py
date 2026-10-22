from parley.settings import Settings
from parley.words import (
    change, command_in, ends_with_send, is_wake, joined, parse, plain, spell, strip_send_phrase, tidy,
)

S = Settings()


def test_plain_drops_wake_phrase_punctuation_and_please():
    assert plain("Hey Claude, scratch that please.", S.wake_phrases) == "scratch that"


def test_a_whole_command_is_a_command():
    assert command_in("Scratch that.", S.wake_phrases) == "scratch"
    assert command_in("Hey cloud, voice off", S.wake_phrases) == "voice off"
    assert command_in("Send it.", S.wake_phrases) == "send"
    assert command_in("Repeat that.", S.wake_phrases) == "repeat"
    assert command_in("Read it back, please.", S.wake_phrases) == "read back"


def test_a_sentence_that_contains_a_command_word_is_not_a_command():
    assert command_in("Stop the deploy if it fails", S.wake_phrases) == ""
    assert command_in("Is the deploy done?", S.wake_phrases) == ""
    assert command_in("Type the function signature for me", S.wake_phrases) == ""


def test_type_before_a_command_types_the_words():
    assert parse("Type stop.", S.wake_phrases) == ("literal", "stop")
    assert parse("Type scratch that", S.wake_phrases) == ("literal", "scratch that")


def test_change_one_word_to_another():
    assert parse("Change staging to production.", S.wake_phrases) == ("change", "staging\tproduction")
    assert parse("Replace foo with bar", S.wake_phrases) == ("change", "foo\tbar")
    assert change("Deploy staging, then test Staging", "staging", "production") == \
        "Deploy staging, then test production"
    assert change("Deploy now", "staging", "production") is None
    assert change("Read the docs", "do", "x") is None  # whole words only


def test_spelling_letters():
    assert spell("m y capital s q l") == "mySql"
    assert spell("alpha bravo dash one") == "ab-1"
    assert spell("abc") == "abc"
    assert parse("Spell A, B, C.", S.wake_phrases) == ("spell", "abc")
    assert spell("hello?? world") == ""


def test_a_message_ending_in_a_send_phrase_is_sent():
    assert ends_with_send("Fix the login page, send it.", S.send_phrases)
    assert ends_with_send("Check the tests. That's it", S.send_phrases)


def test_a_bare_send_phrase_or_a_pause_does_not_end_a_message():
    assert not ends_with_send("send it", S.send_phrases)
    assert not ends_with_send("Fix the login page", S.send_phrases)


def test_the_send_phrase_is_taken_off_the_message():
    assert strip_send_phrase("Fix the login page, send it.", S.send_phrases) == "Fix the login page."
    assert strip_send_phrase("Run the tests send it now", S.send_phrases) == "Run the tests."
    assert strip_send_phrase("Run the tests?", S.send_phrases) == "Run the tests?"


def test_fillers_come_out_and_replacements_go_in():
    assert tidy("Um, fix the, uh, login page", True, {}) == "Fix the login page"
    assert tidy("Run it, um. Then stop.", True, {}) == "Run it. Then stop."
    assert tidy("Um, fix it", False, {}) == "Um, fix it"
    assert tidy("open post gress on get hub", True, {"post gress": "PostgreSQL", "get hub": "GitHub"}) == \
        "Open PostgreSQL on GitHub"
    assert tidy("the summer is here", True, {}) == "The summer is here"  # 'um' inside a word stays


def test_new_words_join_what_was_already_in_the_box():
    assert joined("Earlier text.", "more words") == "Earlier text. more words"
    assert joined("", "more words") == "more words"


def test_the_wake_phrase_survives_a_missed_hey():
    assert is_wake("hey claude", S.wake_phrases)
    assert is_wake("[unk] claude", S.wake_phrases)
    assert is_wake("[unk] cloud", S.wake_phrases)
    assert not is_wake("[unk]", S.wake_phrases)
    assert not is_wake("[unk] [unk] claude", S.wake_phrases)


def test_a_mangled_short_command_still_counts():
    assert command_in("Rea back.", S.wake_phrases) == "read back"
    assert command_in("Scratch dat", S.wake_phrases) == "scratch"
    assert command_in("Top.", S.wake_phrases) == ""  # too short to guess
    assert command_in("Run back", S.wake_phrases) == ""
    assert command_in("Read the error log and fix it", S.wake_phrases) == ""
