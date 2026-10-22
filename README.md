# Parley

**Hands-free voice for the Claude desktop app on Windows.**

Say "Hey Claude", talk, and watch your words appear in Claude's message box as you speak.
Say "send it" to send. Claude's answer is read back to you in a natural voice.

> Parley is an unofficial community project. It is not made by, or connected with, Anthropic.

## What it does

- **Wake phrase.** "Hey Claude" starts listening. Nothing is recorded before that.
- **Live words.** What you say shows up in the message box while you talk, so you can see it's hearing you right.
- **You decide when to send.** End with "send it". Pausing to think never sends anything.
  If you stop talking for 15 seconds, your words stay in the box, unsent.
- **Spoken answers.** Claude's reply is read aloud in a natural voice, without the code, tables or links.
- **Voice commands.** Clear the box, stop the voice, stop Claude, or turn spoken answers off, all by voice.
- **A small status strip.** It stays on top of other windows and shows what Parley is doing. Click **?** for the commands.
- **Private speech recognition.** Your voice is turned into text on your own computer. See [Privacy](#privacy).

## Commands

| Say | What happens |
| --- | --- |
| **Hey Claude**, then talk | Your words appear in the box as you speak |
| …**send it** (at the end) | Sends the message. "send that", "that's it" and "over and out" work too |
| **Hey Claude, send it** | Sends what's already in the box |
| **Hey Claude, scratch that** | Clears the box |
| **Hey Claude, quiet** | Stops reading the current answer |
| **Hey Claude, stop** | Stops Claude's work (presses Esc) |
| **Hey Claude, voice off** / **voice on** | Turns spoken answers off or on |
| **Hey Claude, help** | Shows or hides the command list on the strip |

## The status strip

A small dark strip sits at the bottom right of your screen:

- 🟢 green: waiting for "Hey Claude"
- 🔴 red: listening (your words show under the status line)
- 🟠 orange: working, or a problem it is telling you about
- ⚪ grey: paused

Drag it anywhere, and it remembers the spot. Click **?** to see the commands.

The tray icon (near the clock) can pause listening, stop the voice, turn spoken answers on or off, hide the strip,
open the settings file or the log, and quit.

## Requirements

- Windows 10 or 11
- The [Claude desktop app](https://claude.ai/download). Claude Code users also get spoken answers.
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

To **update**, download the new version and run `install.cmd` again. Your settings are kept.

### First use

1. Open the Claude app and **click its message box once**. That's how Parley learns where to type.
2. Say **"Hey Claude"**, wait for "Yes?", then talk.
3. End with **"send it"**.

## Settings

Open **Tray icon → Open the settings file**. It's at `%USERPROFILE%\.parley\config.toml`, and every setting has a comment.
After a change, quit Parley from the tray and start it again from the Start menu.

The useful ones:

```toml
voice = "en-US-AndrewMultilingualNeural"   # any Edge voice: python -m edge_tts --list-voices
send_phrases = ["send it", "send that", "that's it", "over and out"]
quiet_seconds = 15.0      # stop listening after this much quiet, leaving the text unsent
speaking_level = 0.008    # raise it in a noisy room
microphone = ""           # part of a microphone's name; empty means the Windows default
final_model = "small.en"  # "base.en" is faster on slow computers, "medium.en" is more accurate
```

## Privacy

- **Wake phrase and speech-to-text run on your computer.** Parley uses [Vosk](https://alphacephei.com/vosk/) and
  [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Your voice is never uploaded.
- **The spoken voice is online.** Answers are read aloud by Microsoft's Edge voice service, through
  [edge-tts](https://github.com/rany2/edge-tts), so the text being spoken is sent to Microsoft.
  If you don't want that, say "voice off" or set `speak_replies = false`.
- Parley sends nothing anywhere else, and keeps no recordings.

## Troubleshooting

**The strip says it can't use the microphone.**
Open **Settings → Privacy & security → Microphone**. Turn on *Microphone access*, *Let apps access your microphone*
and *Let desktop apps access your microphone*. Then start Parley again.

**It says "Click the Claude message box once".**
Parley hasn't seen you click a Claude message box yet, or the window moved. Click into the box, then try again.

**It doesn't hear "Hey Claude".**
Speak at a normal volume, close to the mic. Check that the right microphone is the Windows default, or set
`microphone` in the settings.

**Check everything at once.** Open PowerShell and run:

```powershell
& "$env:USERPROFILE\.parley\venv\Scripts\python.exe" -m parley doctor
```

The log is at `%USERPROFILE%\.parley\parley.log`.

## Limits (version 0.1)

- **Windows only, and the Claude desktop app only, for typing.** Parley finds the message box through Windows
  UI Automation, where it is named "Prompt". A future Claude app update could change that and break typing until
  Parley is updated. Spoken answers work in Claude Code too.
- **Parley replaces what's in the box while you talk.** Text that was already there is kept at the front. Don't type
  in the box while Parley is listening.
- **English only** for now. The models are the English ones.
- **"Hey Claude" is heard as common English words**, such as "hey cloud", so similar-sounding speech can wake it.

## Uninstall

Double-click **`uninstall.cmd`**. It stops Parley, takes its hook out of Claude Code, and removes the shortcuts,
the Python environment and the models. Your settings file is kept. Run `uninstall.ps1 -All` to remove that too.

## How it works

```text
microphone ──► Vosk (wake phrase) ──► faster-whisper base.en (live words, every second)
                                            │
                                            ▼
                         Claude message box (UI Automation + paste)
                                            │  "send it"
                                            ▼
                       faster-whisper small.en (final words) ──► Enter
Claude answers ──► Claude Code Stop hook ──► edge-tts ──► speakers
```

| File | Job |
| --- | --- |
| `src/parley/app.py` | Listening loop and one message, start to finish |
| `src/parley/claude_box.py` | Finding and typing into the Claude message box |
| `src/parley/words.py` | Commands and the send phrase |
| `src/parley/ui.py` | Status strip and tray icon |
| `src/parley/speak_reply.py` | The Claude Code hook that reads answers aloud |
| `src/parley/setup.py` | Models, hook, shortcuts, microphone check |
| `src/parley/settings.py` | Settings and file locations |

Run the tests with `python -m pytest`.

## License

MIT. See [LICENSE](LICENSE). The speech models are downloaded from their own projects under their own licenses:
Vosk (Apache 2.0) and Whisper (MIT).
