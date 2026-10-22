import tomllib

from parley.settings import Settings, default_file_text, load


def test_the_written_settings_file_reads_back_as_the_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(default_file_text(), encoding="utf-8")
    assert load(path) == Settings()


def test_the_settings_file_explains_each_setting():
    text = default_file_text()
    assert "# Say one of these to wake Parley." in text
    assert tomllib.loads(text)["voice"] == Settings().voice


def test_values_in_the_file_win_and_unknown_or_wrong_typed_ones_are_ignored(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('voice = "en-GB-RyanNeural"\nquiet_seconds = 20\nspeak_replies = "yes"\nnope = 1\n'
                    'wake_phrases = ["Hey Computer"]\n', encoding="utf-8")
    s = load(path)
    assert s.voice == "en-GB-RyanNeural"
    assert s.quiet_seconds == 20.0
    assert s.speak_replies is True
    assert s.wake_phrases == ["hey computer"]
    assert s.wake_name == "Hey Computer"


def test_a_missing_or_broken_file_gives_the_defaults(tmp_path):
    assert load(tmp_path / "none.toml") == Settings()
    broken = tmp_path / "broken.toml"
    broken.write_text("voice = ", encoding="utf-8")
    assert load(broken) == Settings()
