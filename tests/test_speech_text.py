from parley.speak_reply import to_speech


def test_code_tables_links_and_markdown_are_not_read_aloud():
    reply = """**Done.** See [the PR](https://example.com/pr/1).

| a | b |
|---|---|
| 1 | 2 |

```bash
rm -rf /
```

- First `thing`
"""
    assert to_speech(reply, 900) == "Done. See the PR.\nFirst thing"


def test_long_answers_stop_at_a_sentence():
    reply = "This is one sentence. " * 100
    spoken = to_speech(reply, 200)
    assert len(spoken) <= 200 and spoken.endswith(".")
