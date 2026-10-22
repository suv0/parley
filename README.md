# Parley

**Hands-free voice for Claude on Windows.**

Say "Hey Claude", talk, and watch your words appear in Claude's message box as you speak.
Say "send it" to send. Claude's answer is read back to you in a natural voice.

It works in the Claude desktop app, and in Claude Code (or any other app) wherever your cursor is.

> Parley is an unofficial community project. It is not made by, or connected with, Anthropic.

## What it does

- **Wake phrase or shortcut.** "Hey Claude" or **Ctrl+Alt+H** starts listening. Nothing is recorded before that.
- **Live words.** In the Claude app, what you say shows up in the message box while you talk. In other apps, it shows on
  the status strip, then is typed when you finish.
- **You decide when to send.** End with "send it", or press the shortcut again. Pausing to think never sends anything,
  unless you choose the "send on a pause" mode. If you stop talking for 15 seconds, your words stay typed, unsent.
- **Spoken answers.** Claude's reply is read aloud, without the code, tables or links. Pick the voice and the speed.
  "Repeat that" plays it again.
- **Hear and fix your message.** "Read it back" reads your message to you. "Change staging to production" fixes a word.
  "Spell kilo echo" types letters.
- **Hears you right.** Add your own names and jargon to a word list, and fix words it keeps getting wrong. "Um" and
  "uh" are taken out. When Parley isn't sure it heard you, it doesn't send: it types the words and reads them back.
- **A small status strip.** It stays on top of other windows and shows what Parley is doing and where the words will go.
  Click **?** for the commands. There's a large, high-contrast version too.
- **Short beeps** tell you when it starts and stops listening, so you don't have to watch the screen.
- **Private speech recognition.** Your voice is turned into text on your own computer. See [Privacy](#privacy).

## Commands

Say **Hey Claude** (or press **Ctrl+Alt+H**) first.

| Say | What happens |
| --- | --- |
| *anything*, then …**send it** | Types it and sends it. "send that", "that's it" and "over and out" work too |
| **send it** | Sends what's already typed |
| **scratch that** | Clears the box |
| **read it back** | Reads your message aloud |
| **change** *word* **to** *word* | Fixes a word in the box ("change staging to production") |
| **spell** *letters* | Types letters: "spell kilo uniform bravo echo" types *kube*. Say "capital" for a capital letter |
| **type** *command* | Types a command word instead of running it: "type stop" types *stop* |
| **repeat that** | Reads Claude's last answer again |
| **quiet** | Stops reading the current answer |
| **stop** | Stops Claude's work (presses Esc) |
| **voice off** / **voice on** | Turns spoken answers off or on |
| **help** | Shows or hides the command list on the strip |

Spelling works best with the NATO alphabet (alpha, bravo, charlie…). Single letters are easy to mishear.

## Where the words go

- **The Claude app is in front:** its message box. Click it once after installing, so Parley knows where it is.
  Your words appear as you talk, and every command above works.
- **Any other app is in front** (a terminal running Claude Code, an editor, a chat): wherever your cursor is.
  Parley can't read other apps, so your words show on the strip while you talk and are typed once when you finish.
  "Read it back" reads the last thing it typed. "Change" works in the Claude app only.

To always use one or the other, set `target` in the settings.

## The status strip

A small dark strip sits at the bottom right of your screen:

- 🟢 green: waiting for "Hey Claude"
- 🔴 red: listening. It shows where the words are going, and your words as they're heard
- 🟠 orange: working, or a problem it is telling you about
- ⚪ grey: paused

Drag it anywhere, and it remembers the spot. Click **?** to see the commands.

The tray icon (near the clock) can:

- pause listening;
- stop the voice;
- turn spoken answers on or off;
- hide the strip;
- show the help;
- open the microphone settings, the settings file or the log;
- restart Parley after a settings change;
- quit.

## Accessibility

- **No mouse or keyboard needed** after setup. Every command works by voice.
- **No screen needed.** Beeps mark the start and end of listening. Problems are spoken. "Read it back" and
  "repeat that" let you hear your message and the answer.
- **A keyboard shortcut instead of the wake phrase**, for noisy rooms, or if the wake phrase is hard for you to say.
  Set `hotkey` to any key combination.
- **Large, high-contrast strip:** set `strip_size = "large"` and `high_contrast = true`.
- **Slower or faster speech:** set `speaking_rate`, for example `-30` for slower.
- **More time to think:** raise `quiet_seconds`. Nothing sends until you say so.

## Requirements

- Windows 10 or 11.
- The [Claude desktop app](https://claude.ai/download), or Claude Code in a terminal.
- Python 3.11, 3.12 or 3.13. The installer offers to install Python 3.12 if you have none.
- A microphone. Headphones are best, so the mic doesn't hear the answers being read aloud.
- About 1 GB of disk space, and an internet connection for the first install.

## Install

1. Download this project: **Code → Download ZIP** on GitHub, then unzip it.
   Or, with git, run `git clone https://github.com/suv0/parley`.
2. Double-click **`install.cmd`**.

The installer:

- makes a private Python environment in `%USERPROFILE%\.parley`, so it never touches your other Python projects;
- downloads the speech models (about 640 MB, only once);
- turns on spoken answers in Claude Code;
- adds Parley to the Start menu and sets it to start with Windows;
- checks your microphone, then starts Parley.

To **update**, download the new version and run `install.cmd` again. Your settings are kept, and new settings are added
with their defaults.

### First use

1. Open the Claude app and **click its message box once**. That's how Parley learns where to type.
2. Say **"Hey Claude"**, wait for the beep, then talk.
3. End with **"send it"**.

## Settings

Open **Tray icon → Open the settings file**. It's at `%USERPROFILE%\.parley\config.toml`, and every setting has a
comment. After a change, choose **Restart** in the tray menu.

The useful ones:

```toml
hotkey = "ctrl+alt+h"   # or "" for none
send_mode = "phrase"        # "pause" also sends when you stop talking for pause_seconds
target = "auto"             # "claude-app" or "cursor" to always use one
words = ["Kubernetes", "PostgreSQL", "Priya"]          # names and jargon to expect
replacements = { "get hub" = "GitHub" }                # "what it hears" = "what to type"
language = "en"             # "de", "es", "fr", "hi", "bn", ...: run install.cmd again after changing it
voice_engine = "edge"       # "windows" for the offline Windows voices
voice = "en-US-AndrewMultilingualNeural"   # any Edge voice: python -m edge_tts --list-voices
speaking_rate = 0           # -30 slower, 25 faster
cue_sounds = true           # beeps instead of saying "Yes?"
quiet_seconds = 15.0        # stop listening after this much quiet, leaving the text unsent
speaking_level = 0.008      # raise it in a noisy room
microphone = ""             # part of a microphone's name; empty means the Windows default
final_model = "small.en"    # "base.en" is faster on slow computers, "medium.en" is more accurate
strip_size = "normal"       # or "large"
high_contrast = false
```

## Privacy

- **The wake phrase and speech-to-text run on your computer.** Parley uses [Vosk](https://alphacephei.com/vosk/) and
  [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Your voice is never uploaded.
- **The natural voice is online.** With `voice_engine = "edge"` (the default), answers are read aloud by Microsoft's
  Edge voice service through [edge-tts](https://github.com/rany2/edge-tts), so the text being spoken is sent to
  Microsoft. Set `voice_engine = "windows"` to use the offline Windows voices instead. If the Edge service can't be
  reached, Parley uses the Windows voice anyway.
- Parley sends nothing anywhere else, and keeps no recordings.

## Troubleshooting

**The strip says it can't use the microphone.**
Open **Settings → Privacy & security → Microphone**. Turn on *Microphone access*, *Let apps access your microphone*
and *Let desktop apps access your microphone*. Then start Parley again.

**It says "Click the Claude message box once".**
Parley hasn't seen you click a Claude message box yet, or the window moved. Click into the box, then try again.

**It doesn't hear "Hey Claude".**
Speak at a normal volume, close to the mic. Check that the right microphone is the Windows default, or set
`microphone` in the settings. The shortcut (Ctrl+Alt+H) always works.

**The strip says the shortcut is taken by another app.**
Another program already uses that key combination. Set `hotkey` to a different one, such as `"ctrl+shift+f9"`, then
choose Restart in the tray menu.

**It typed in the wrong app.**
With `target = "auto"`, words go to the app that was in front when you woke Parley. The strip shows where. Set
`target = "claude-app"` to always use the Claude app.

**It keeps mishearing a name.** Add it to `words`, or add the wrong version to `replacements`.

**Check everything at once.** Open PowerShell and run:

```powershell
& "$env:USERPROFILE\.parley\venv\Scripts\python.exe" -m parley doctor
```

The log is at `%USERPROFILE%\.parley\parley.log`.

## Limits

- **Windows only.**
- **The Claude app's box is found through Windows UI Automation**, where it is named "Prompt". A Claude app update
  could change that. Until Parley is updated, set `target = "cursor"` and click into the box yourself.
- **Parley replaces what's in the Claude box while you talk.** Text that was already there is kept at the front.
  Don't type in the box while Parley is listening.
- **The wake phrase and commands are English**, even when `language` is set to another language.
- **"Hey Claude" is heard as common English words**, such as "hey cloud", so similar-sounding speech can wake it.

## Uninstall

Double-click **`uninstall.cmd`**. It stops Parley, takes its hook out of Claude Code, and removes the shortcuts,
the Python environment and the models. Your settings file is kept. Run `uninstall.ps1 -All` to remove that too.

## How it works

```text
microphone ──► Vosk (wake phrase)  or  Ctrl+Alt+H
                    │
                    ▼
        faster-whisper base.en (live words, every second) ──► Claude box / strip
                    │  "send it"
                    ▼
        faster-whisper small.en (final words, word list, fillers out) ──► type ──► Enter
Claude answers ──► Claude Code Stop hook ──► Edge or Windows voice ──► speakers
```

| File | Job |
| --- | --- |
| `src/parley/app.py` | Listening loop and one message, start to finish; the commands |
| `src/parley/targets.py` | Where the words go: the Claude box, or wherever the cursor is |
| `src/parley/words.py` | Commands, the send phrase, spelling, fillers and replacements |
| `src/parley/voice.py` | Edge and Windows voices, beeps |
| `src/parley/hotkey.py` | The keyboard shortcut |
| `src/parley/ui.py` | Status strip and tray icon |
| `src/parley/speak_reply.py` | The Claude Code hook that reads answers aloud |
| `src/parley/setup.py` | Models, hook, shortcuts, microphone check |
| `src/parley/settings.py` | Settings and file locations |

Run the tests with `python -m pytest`. `tests/test_listening.py` plays recorded speech through the whole listening
loop. It runs when the speech models are installed and the internet is reachable, and is skipped otherwise.

## Ideas borrowed from

The word list, filler removal and "type"/"correct" commands follow Windows Voice Access and Wispr Flow. The
choice between "send on a phrase" and "send on a pause" follows mcp-voice-hooks. Typing at the cursor follows Bol.
Checking unclear messages follows handsfree-claude.

## License

MIT. See [LICENSE](LICENSE). The speech models are downloaded from their own projects under their own licenses:
Vosk (Apache 2.0) and Whisper (MIT).
