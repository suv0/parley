from utter import settings as paths
from utter import spoken
from utter.spoken import Spoken, for_listening, paragraphs, parse, plain, split

WRITTEN = """**Done.** Merged [suv0/prsm#2](https://github.com/suv0/prsm/pull/2) and fixed `smoke-local.mjs`.

| Repo | PR |
|---|---|
| prsm | #2 |

```bash
npm test
```

- Commit `6deaebf` is on main
"""


def test_plain_drops_code_tables_links_and_hashes():
    text = plain(WRITTEN)
    for unwanted in ("```", "|", "https", "**", "6deaebf", "npm test"):
        assert unwanted not in text
    assert text.startswith("Done. Merged suv0/prsm")
    assert "Commit is on main." in text


def test_a_long_plain_answer_is_split_into_short_now_and_the_rest_on_request():
    text = " ".join(f"Sentence number {i} is here." for i in range(40))
    out = split(text)
    assert len(out.short) <= 300 and out.short.endswith(".")
    assert out.more and " ".join(out.more).startswith("Sentence number")
    assert out.short + " " + " ".join(out.more) == text  # nothing is lost


def test_claudes_reply_is_read_from_its_tags():
    reply = "<short>I merged the pull request that adds the demo. CI passes.</short>\n<more>First thing.\n\nSecond thing.</more>"
    out = parse(reply)
    assert out == Spoken("I merged the pull request that adds the demo. CI passes.", ["First thing.", "Second thing."], "claude")


def test_a_reply_without_tags_is_still_spoken():
    assert parse("All done, nothing else to do.").short == "All done, nothing else to do."


def test_long_paragraphs_are_split_at_sentences():
    parts = paragraphs("One two three. " * 100, longest=200)
    assert all(len(p) <= 200 for p in parts)
    assert all(p.endswith(".") for p in parts)


def test_the_rewrite_is_used_when_it_works(monkeypatch):
    monkeypatch.setattr(spoken, "rewrite", lambda text, s: "<short>The tests pass.</short><more></more>")
    out = for_listening(WRITTEN, paths.Settings())
    assert out.short == "The tests pass." and out.more == [] and out.by == "claude"


def test_a_failed_or_slow_rewrite_falls_back_to_the_plain_version(monkeypatch):
    def slow(text, s):
        raise TimeoutError("took too long")

    monkeypatch.setattr(spoken, "rewrite", slow)
    out = for_listening(WRITTEN, paths.Settings())
    assert out.by == "rules" and out.short.startswith("Done.")


def test_plain_mode_never_calls_claude(monkeypatch):
    monkeypatch.setattr(spoken, "rewrite", lambda *_: (_ for _ in ()).throw(AssertionError("called")))
    out = for_listening(WRITTEN, paths.Settings(spoken_answers="plain"))
    assert out.by == "rules"
