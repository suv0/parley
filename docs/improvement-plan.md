# Utter improvement plan

Goal: Utter should just work, for someone who never looks at the screen. Say "Hey Claude", talk,
see your words appear as fast as you speak, send, and hear an answer that sounds like a person
talking to you, not a page being read out.

This plan comes from three things:

- **The code.** Every file in `src/utter`.
- **Your log.** `~/.utter/utter.log` from 22 to 23 October: 13 wakes, and what happened after each.
- **Research.** Voice design guides from Amazon, Google and Apple, Microsoft Voice Access, Dragon,
  Talon, wake-word engines and papers, and the Claude Code hooks docs. Sources are at the end.

Phases are in priority order. Each step is a small change with its own tests, pushed on its own.

---

## What the log shows

| What happened | Evidence | Cause in the code |
|---|---|---|
| Typing falls minutes behind your voice | 2 minutes of speech took **11½ minutes** to finish (00:34 to 00:46) | Every second, `hear()` re-transcribes **all** the audio since the wake. The work grows with the square of the message length, so the mic queue backs up. |
| It wakes without "Hey Claude" | At least 9 of 13 wakes were not you: a Facebook video, songs, its own voice | The small Vosk model is told to pick the closest phrase from `wake_phrases`, so TV speech often comes out as "okay claude" or "hey cloud". Nothing checks it twice. |
| It wakes itself up | 3 wakes came within a minute of one of its own spoken answers (00:18, 01:15, 03:33) | While an answer plays through the speakers, the wake detector keeps listening, and answers often say "Claude". |
| A beep, then later "a problem" | "I didn't hear anything" after false wakes | After a false wake it waits 8 s, then reports a problem out loud instead of quietly going back to sleep. |
| Junk typed or pasted | "Thank you.", "We'll see you next time" ×3, TV dialogue pasted toward a **browser window** | Whisper invents these on noise or music, a known hallucination. Utter types whatever comes back, and in "cursor" mode it pastes into whatever window was last in front. |
| "Couldn't type that" | 7 tracebacks: `OpenClipboard ... Access is denied` | Another app held the clipboard. `paste()` tries once and gives up. |
| Long answers cut off | `max_spoken_chars = 900` | The reply is cut at a sentence near 900 characters, and nothing tells you there was more. |
| Answers read like a document | "PR number 456", file paths, half-sentences after code is removed | `to_speech()` only strips markdown with regexes. Nothing rewrites the text for listening. |

---

## Phase 1: fix what's broken

### 1.1 Words appear as fast as you speak (the typing lag)
- **Lock in finished text.** Keep the transcript of finished speech, ended by a pause of about 0.7 s
  or by segments faster-whisper reports as complete. Live updates only re-transcribe the
  unfinished tail (the last 5 to 10 s), so each update costs the same however long you talk.
- **Append instead of retyping.** Add new words at the end of the box. Rewrite only the tail when
  a correction changes it. No more select-all and paste every second, and no flicker.
- **Never fall behind.** If live updates can't keep up, skip one instead of queueing work. The
  queue only ever holds raw audio.
- **Keep the final pass accurate but in the background.** `small.en` still makes the final pass on
  "send it", over the locked-in segments plus the tail, so it isn't one giant re-run.
- **Stop at the real limit.** `max_message_seconds` is also checked on the wall clock, so a message
  can never run 11 minutes again.
- **Test:** feed a recorded 3-minute message faster than real time, and check that each live
  update stays under about 1 s and the final text matches.

### 1.2 Only wake for "Hey Claude"
Layered checks: a sound has to pass every one before the beep.
1. **Not while it's talking.** Utter's own answers can't wake it. While an answer plays, a wake
   counts only if it also passes check 3, and the words being spoken don't contain the wake
   phrase at that moment. The shortcut always works.
2. **Vosk, stricter.** Turn on word confidence (`SetWords(True)`). Accept only when both words are
   confident (start near 0.85 and tune on recordings), and the phrase lasts a believable time
   (0.4 to 1.5 s). Add decoy phrases ("hey clyde", "okay", "hey google") so near-misses land on
   a decoy instead of a wake phrase.
3. **Second check with Whisper.** Re-transcribe the 1.5 s around the wake with `small.en`, and
   reject it if `no_speech_prob` is high or the text isn't close to a wake phrase. This costs
   about a quarter of a second, only after a candidate wake.
4. **Try a real wake-word model.** A community openWakeWord "hey claude" model exists (Apache-2.0,
   about 200 KB, offline, ONNX works on Windows). Benchmark it against layers 2 and 3 on the same
   recordings, and switch only if it is clearly better. Porcupine is ruled out: it needs an
   online key and the free tier is reportedly ending.
5. **Measure, don't guess.** Build a test bench of recorded audio: TV, YouTube, music, typing,
   Utter's own answers, and you saying the wake phrase from across the room. Count false wakes
   per hour and missed wakes. Target under 0.5 false wakes per hour of TV, which is what
   commercial assistants aim for, with no more than 1 in 20 real wakes missed.
6. **Sleep mode.** "Hey Claude, go to sleep" (or the tray) means only "Hey Claude, wake up" works,
   and it needs the stricter check. Use it during a film or a meeting.

**What testing showed, and what was built.** The ideas above were tried on Edge voices, real
phrases and look-alikes:
- **Vosk word confidence can't separate them.** A real "Hey Claude" often scores only 0.5 to 0.6,
  the same as look-alikes.
- **Whisper can't confirm the phrase.** It heard a real "Hey Claude" as "ECLOD", "Here you go" or
  "High clone", even with the phrase as a hint.
- **The openWakeWord "hey claude" model** almost never false-woke (1 of 96 tries), but it missed
  a plain "Hey Claude" in 5 of 8 voices. It's too deaf to be the main detector.
- **What does separate them is loudness around the phrase.** You say "Hey Claude" on its own,
  louder than the room. A line in a film sits between other lines at the same loudness. So Utter
  now finds the wake phrase in what Vosk heard, even inside a longer stretch when a TV runs behind
  you, and wakes only when the loudest sound in the second before and the 0.8 s after is under
  half the phrase's loudness.
- **Self-wake guard:** while an answer that mentions "Claude" is playing, spoken wakes are ignored.
- **Decoy words** ("hey", "okay", "cloudy", ...) give near-misses somewhere else to land.
- **Bench results:** a real wake works in at least 5 of 6 voices, and over quieter TV. The wake
  phrase inside dialogue (three lines, three voices) never wakes it.
- **Vosk crash:** making a new recognizer after every message, with word times on, crashes Vosk
  0.3.45 after a few dozen. Utter keeps one recognizer and resets it.

### 1.3 Recover from a false wake quietly
- **No speech, no fuss.** If nothing is said within about 5 s of the beep, play a soft "cancelled"
  tone and go back to waiting. No spoken "problem" and no orange strip.
- **"Cancel" and "never mind"** end listening at once and type nothing.
- **Don't type hallucinations.** Drop segments where Whisper is unsure (high `no_speech_prob`, low
  `avg_logprob`, high compression ratio), the same sentence repeated, and known phantom phrases
  ("thank you", "thanks for watching", "see you next time", "subscribe") when they're all there is.
- **Be careful outside the Claude app.** In cursor mode, never paste into a window unless real
  speech was confirmed, and say where it's going ("typing into Notepad") the first time.

### 1.4 Typing never fails on a busy clipboard
- **Retry.** Try `OpenClipboard` again for about 1 s with short waits.
- **Fall back.** If the clipboard is still busy, set the box text through UI Automation's
  ValuePattern, then as a last resort type with Unicode `SendInput`.

---

## Phase 2: answers that sound like a person

### 2.1 Claude writes the spoken version
- **A second, fast pass.** The hook sends the reply to `claude-haiku-5-5`, the fastest current
  Claude model (a fraction of a cent per answer), with spoken-style rules:
  - Lead with the result in one or two short sentences, like a colleague talking.
  - **Describe things, don't read identifiers.** "the pull request that adds the demo animation",
    not "PR number 2". The same goes for file paths, hashes, error codes and links ("there's a
    link to the docs on screen").
  - Round numbers that don't need precision ("about two thousand lines").
  - Turn code into what it does ("it adds a retry around the clipboard"), not the characters.
  - End with a question only when Claude needs something from you.
  - Keep every decision and every next step.
- **How it calls Claude**, chosen at setup:
  - **API key** (best): direct Messages API call, about 1 s.
  - **Your Claude login:** `claude -p --model claude-haiku-5-5` with hooks turned off, so the
    rewrite doesn't trigger Utter's own read-aloud hook again. Slower to start; to be measured.
  - **Neither:** today's regex cleanup, improved.
- **Never stuck.** If the rewrite takes longer than about 3 s, or fails, it speaks the regex
  version, so speech never breaks because the network did.
- **Option, no second call:** a "Spoken" Claude Code output style makes Claude add a short
  `<spoken>` summary to its own reply, which the hook reads. It's free and instant, but it
  changes what you see on screen, so it stays off by default.

### 2.2 Long answers: short first, more on request
- **No silent cut.** Speak the short version, then "There's more. Want the details?"
- **"More" / "tell me more"** reads the rest, a paragraph at a time, rewritten the same way.
- **Start speaking sooner.** Speech is made one sentence at a time and the first plays while the
  next is made. No 900-character limit.
- **Controls while it reads:** "skip", "go back", "pause", "resume", "slower", "faster", "quiet",
  "repeat that".

### 2.3 Read the right answers, at the right time
- **Only your sessions.** Today every Claude Code session on the PC is read aloud, including
  background ones. Add a choice: read all answers, or only answers to messages you sent by voice
  (Utter records when it sent and to which window).
- **Don't lose answers.** An answer that arrives while you're talking is silently dropped today.
  Hold it, then say "Claude answered. Say repeat that to hear it."
- **Hear what's happening.** A soft "thinking" tone after sending, so you know Claude is working
  without looking, and a short tone before an answer starts.

---

## Phase 3: easier and more natural to use

1. **Help you can hear.** "Hey Claude, what can I say?" speaks the three to five commands that
   make sense right now (idle, dictating, or answer playing). Today help only appears on the strip.
2. **"What's happening?"** speaks the state: listening, Claude working, voice off, or sleeping.
3. **Specific, honest problems.** Say what went wrong and what to do: "The Claude app isn't open",
   "I couldn't type into the box. Click it once". After two failures in a row, offer help instead
   of repeating.
4. **Interrupting always works.** The shortcut, or "Hey Claude" (with the strict check), stops an
   answer at once.
5. **Change settings by voice.** "Speak slower", "speak faster", "use the offline voice", "turn the
   beeps off", saved to `config.toml`, so nobody has to edit a file.
6. **Check before sending when it matters.** Long messages, or ones heard with low confidence, are
   read back briefly ("Sending: fix the login page...") with a moment to say "wait".
7. **Better corrections.** "Correct that" reads two or three alternatives from Whisper as numbered
   choices ("say one, two or three"), the way Windows Voice Access does.
8. **Distinct sounds for every state.** Listening, sent, thinking, answer, cancelled and error each
   get their own short tone, and every one can be turned off.

---

## Phase 4: privacy and quality

- **Privacy.** The log stores the text of everything heard, including TV and other people.
  Log only lengths and confidence by default, with full text as an opt-in debug setting.
- **Tuning data.** Log wake confidence, the second check's result, and the outcome, so thresholds
  can be tuned from real use.
- **Regression tests.** The audio test bench from 1.2 and the 3-minute lag test from 1.1 run in
  CI, so neither problem comes back.

---

## Order of work

1. **1.1** typing lag
2. **1.2** steps 1 to 3 and 5: wake checks and the test bench
3. **1.3** quiet recovery
4. **1.4** clipboard
5. **2.1** and **2.2**: spoken answers and long answers
6. **2.3** and **Phase 3**
7. **1.2** steps 4 and 6 (openWakeWord, sleep mode) and **Phase 4**

Each step gets tests, a real try on this PC, and a push to `main`, as with the leftover-audio fix.

---

## Sources

- Wake-word misactivation from TV, about 1 per hour: [PoPETs 2020](https://petsymposium.org/popets/2020/popets-2020-0072.php)
- Vosk grammar and word confidence: [example](https://github.com/alphacep/vosk-api/blob/master/python/example/test_words.py), [adaptation](https://alphacephei.com/vosk/adaptation)
- openWakeWord: [README](https://github.com/dscripka/openWakeWord); community ["hey claude" model](https://huggingface.co/gdiamos/hey-claude)
- Porcupine: [benchmark](https://picovoice.ai/docs/benchmark/wake-word/); free tier ending (secondhand) [forum](https://community.home-assistant.io/t/fyi-picovoice-confirmed-free-tier-accesskeys-will-stop-working-after-june-30-2026/1012744)
- Silero VAD: [GitHub](https://github.com/snakers4/silero-vad)
- Whisper hallucination, worse with long pauses: ["Careless Whisper"](https://arxiv.org/abs/2402.08021)
- Brevity, lists, "hear more": [Alexa one-breath test](https://developer.amazon.com/en-US/blogs/alexa/post/531ffdd7-acf3-43ca-9831-9c375b08afe0/things-every-alexa-skill-should-do-pass-the-one-breath-test), [What Alexa says](https://developer.amazon.com/fr/designing-for-voice/what-alexa-says/)
- Errors and confirmations: [Google errors](https://developers.google.com/assistant/conversation-design/errors), [Google confirmations](https://developers.google.com/assistant/conversation-design/confirmations)
- Barge-in, attention states, earcons: [Alexa Auto](https://developer.amazon.com/en-US/docs/alexa/alexa-auto/invoking-alexa.html)
- Dialog with no screen: [Apple WWDC20](https://developer.apple.com/videos/play/wwdc2020/10071/)
- Writing for voice output: [LiveKit](https://docs.livekit.io/agents/build/prompting), [AssemblyAI](https://www.assemblyai.com/docs/voice-agents/voice-agent-api/prompting-guide.md)
- Sentence-by-sentence speech: [ElevenLabs latency](https://elevenlabs.io/blog/voice-agent-latency-optimization), [edge-tts](https://github.com/rany2/edge-tts)
- Hook payload (`last_assistant_message`, async): [Claude Code hooks](https://code.claude.com/docs/en/hooks); headless mode: [docs](https://code.claude.com/docs/en/headless); output styles: [docs](https://code.claude.com/docs/en/output-styles)
- Current models: [Claude models](https://platform.claude.com/docs/en/about-claude/models/overview)
- Voice Access commands and correction: [command list](https://support.microsoft.com/en-us/topic/voice-access-command-list-dac0f091-87ce-454d-8d57-bef38d3d8563), [correcting text](https://support.microsoft.com/en-us/accessibility/windows/voice-access/correct-text-with-voice)
- Dragon sleep mode: [Nuance](https://nuance.com/products/help/dragon/dragon-for-mac/enx/Content/Introduction/Microphone/MicrophoneModes.html)
