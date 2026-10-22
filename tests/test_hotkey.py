from parley.hotkey import parse


def test_shortcuts_are_understood():
    assert parse("ctrl+alt+space") == (0x2 | 0x1, 0x20)
    assert parse("Ctrl + Shift + F9") == (0x2 | 0x4, 0x78)
    assert parse("win+k") == (0x8, ord("K"))


def test_a_shortcut_needs_one_real_key():
    assert parse("ctrl+alt") is None
    assert parse("ctrl+banana") is None
