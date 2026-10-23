import pytest

win32clipboard = pytest.importorskip("win32clipboard")
keyboard = pytest.importorskip("pywinauto.keyboard")

from utter import targets  # noqa: E402


def test_a_busy_clipboard_is_tried_again(monkeypatch):
    tries = []

    def open_clipboard(*_):
        tries.append(1)
        if len(tries) < 3:
            raise OSError("Access is denied.")

    monkeypatch.setattr(win32clipboard, "OpenClipboard", open_clipboard)
    assert targets.open_clipboard(seconds=1)
    assert len(tries) == 3


def test_a_clipboard_that_stays_busy_gives_up(monkeypatch):
    monkeypatch.setattr(win32clipboard, "OpenClipboard", lambda *_: (_ for _ in ()).throw(OSError("busy")))
    assert not targets.open_clipboard(seconds=0.2)


def test_paste_types_the_words_when_the_clipboard_stays_busy(monkeypatch):
    typed, pressed = [], []
    monkeypatch.setattr(targets, "open_clipboard", lambda seconds=1.0: False)
    monkeypatch.setattr(keyboard, "send_keys", lambda keys, **_: (typed if _ else pressed).append(keys))
    targets.paste("Fix (the) login\nnow")
    assert typed == ["Fix {(}the{)} login now"]  # brackets escaped, no Enter that would send it
    assert pressed == []
