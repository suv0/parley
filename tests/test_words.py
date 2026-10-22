from parley.settings import Settings
from parley.words import command_in, ends_with_send, joined, plain, strip_send_phrase

S = Settings()


def test_plain_drops_wake_phrase_punctuation_and_please():
    assert plain("Hey Claude, scratch that please.", S.wake_phrases) == "scratch that"


def test_a_whole_command_is_a_command():
    assert command_in("Scratch that.", S.wake_phrases) == "scratch"
    assert command_in("Hey cloud, voice off", S.wake_phrases) == "voice off"
    assert command_in("Send it.", S.wake_phrases) == "send"


def test_a_sentence_that_contains_a_command_word_is_not_a_command():
    assert command_in("Stop the deploy if it fails", S.wake_phrases) == ""
    assert command_in("Is the deploy done?", S.wake_phrases) == ""


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


def test_new_words_join_what_was_already_in_the_box():
    assert joined("Earlier text.", "more words") == "Earlier text. more words"
    assert joined("", "more words") == "more words"
