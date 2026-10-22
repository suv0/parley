from parley.setup import HOOK_MARK, with_hook, without_hook

OTHER = {"type": "command", "command": "mempalace hook run --hook stop", "timeout": 30}
COMMAND = rf'"C:\venv\Scripts\python.exe" -m {HOOK_MARK}'


def parley_hooks(settings):
    return [h for g in settings["hooks"]["Stop"] for h in g["hooks"] if HOOK_MARK in h["command"]]


def test_adding_keeps_every_other_hook_and_setting():
    before = {"theme": "dark", "hooks": {"Stop": [{"hooks": [OTHER]}], "SessionStart": [{"hooks": [OTHER]}]}}
    after = with_hook(before, COMMAND)
    assert after["theme"] == "dark"
    assert after["hooks"]["SessionStart"] == before["hooks"]["SessionStart"]
    assert after["hooks"]["Stop"][0] == {"hooks": [OTHER]}
    assert parley_hooks(after) == [{"type": "command", "command": COMMAND, "timeout": 60, "async": True}]


def test_adding_twice_leaves_one_hook():
    once = with_hook({}, COMMAND)
    assert len(parley_hooks(with_hook(once, COMMAND))) == 1


def test_removing_takes_out_only_parleys_hook():
    mixed = {"hooks": {"Stop": [{"hooks": [OTHER, {"type": "command", "command": COMMAND}]}]}}
    assert without_hook(mixed) == {"hooks": {"Stop": [{"hooks": [OTHER]}]}}
    assert without_hook(with_hook({}, COMMAND)) == {}


def test_adding_does_not_change_the_settings_passed_in():
    before = {"hooks": {"Stop": [{"hooks": [OTHER]}]}}
    with_hook(before, COMMAND)
    assert before == {"hooks": {"Stop": [{"hooks": [OTHER]}]}}
