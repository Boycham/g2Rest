# Voice spike notes (backend/voice)

Status: working end to end against the live ElevenLabs APIs (2026-10-18): Scribe realtime STT,
then a text-only agent, then client tools, then `order.py`. Docs read 2026-10-17. Items still
marked `TO-VERIFY` were not exercised by the run.

## What the docs say (checked)

### Scribe realtime STT
Docs: [API ref](https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime),
[commit strategies](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/transcripts-and-commit-strategies),
[event reference](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/event-reference),
[server-side streaming](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/server-side-streaming)

- Endpoint `wss://api.elevenlabs.io/v1/speech-to-text/realtime`. Auth is the `xi-api-key` header
  (backend) or a single-use `token` query param (client side).
- `model_id=scribe_v2_realtime`, the only allowed value. `audio_format=pcm_16000` (the default) is
  16-bit LE mono at 16 kHz, so G2 mic frames go through unchanged. Only mono is supported.
- `commit_strategy`: `manual` (the default), `vad`, or `turn_prediction`. VAD settings:
  `vad_silence_threshold_secs`, `vad_threshold`, `min_speech_duration_ms`, `min_silence_duration_ms`.
  The docs recommend VAD for mic input.
- Client sends `{"message_type":"input_audio_chunk","audio_base_64":…,"commit":bool,"sample_rate":16000}`.
  All four fields are required. `previous_text` is allowed on the first chunk only.
- Server sends `session_started`, `partial_transcript` (later ones replace earlier ones), and
  `committed_transcript` (final for that segment; there is no `final_transcript` event). Errors
  come as `message_type` values like `auth_error`, `input_error`, `commit_throttled`, …, sent
  before the socket closes.
- Transcription starts after the first ~2 s of audio. 100 ms frames should be fine; there is a
  chunk-size-exceeded error for chunks that are too large, but the docs don't give the limit.
- The optional `keepalive_interval_ms` makes the server send an empty `partial_transcript` about
  once per interval. It's for clients or proxies that close idle sockets during long silences. Not
  used: we stream silence frames instead.
- **There is no separate "close" message in the Scribe protocol.** Our close sequence is about 2 s
  of trailing silence, then a final chunk with `commit: true`, then wait up to 5 s for the
  `committed_transcript`, then close the socket. Verified live: `commit: true` is accepted with
  `commit_strategy=vad`.
- `keyterms` ([realtime](https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime),
  [batch](https://elevenlabs.io/docs/api-reference/speech-to-text/convert), extra cost per the docs).
  Verified live (branch `devin/voice-crowd`): realtime takes the query parameter **repeated**
  (`keyterms=Verity&keyterms=Halibut`); a JSON array in one parameter is not accepted, and a term over
  20 characters is rejected, at most 50 terms. Batch takes repeated `keyterms` multipart fields (200 OK;
  a term with `<` is a 400). `commands.keyterms()` builds the list from the wake word, the command words,
  the staff in `data/floor.json`, one..eight and the dishes (+aliases) in `data/menu.json`, trimmed to
  each endpoint's limits. `vad_threshold` (default 0.4, echoed in `session_started`) and
  `filter_background_audio=true` are also accepted on realtime.

### Agents: text-only (chat) mode
Docs: [chat mode](https://elevenlabs.io/docs/eleven-agents/guides/chat-mode),
[create agent](https://elevenlabs.io/docs/api-reference/agents/create),
[agent WebSocket](https://elevenlabs.io/docs/eleven-agents/api-reference/eleven-agents/websocket),
[signed URL](https://elevenlabs.io/docs/api-reference/conversations/get-signed-url)

- Set `conversation_config.conversation.text_only = true` on the agent. A runtime override also
  exists, but the agent's Security tab has to allow it, so we set it on the agent instead.
- Create with `POST /v1/convai/agents/create`. The prompt goes in
  `conversation_config.agent.prompt.prompt`, plus `llm`, `temperature` (default 0) and `tool_ids`
  (inline `tools` is deprecated). The `llm` enum includes `gemini-2.5-flash` (our default),
  `gpt-4.1-mini`, `claude-haiku-4-5`, and others.
- Conversation socket: `wss://api.elevenlabs.io/v1/convai/conversation?agent_id=…`. The backend
  gets a signed URL from `GET /v1/convai/conversation/get-signed-url?agent_id=…` with
  `xi-api-key`, so the key never leaves the backend.
- Client → server: `conversation_initiation_client_data`, `user_message {text}`,
  `pong {event_id}`, `client_tool_result {tool_call_id, result: string, is_error}`, and
  `contextual_update`.
- Server → client: `conversation_initiation_metadata`, `ping {ping_event.event_id}`,
  `agent_response {agent_response_event.agent_response}`,
  `client_tool_call {client_tool_call: {tool_name, tool_call_id, parameters, event_id, expects_response}}`,
  and `agent_tool_response`.
- Chat mode has its own concurrency pool, 25× the voice limits (Free: 100 chat conversations).

### Tools: client vs server (webhook)
Docs: [client tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/client-tools),
[server tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/server-tools),
[create tool](https://elevenlabs.io/docs/api-reference/tools/create)

- Create with `POST /v1/convai/tools {"tool_config": {"type":"client", name, description,
  parameters, expects_response, response_timeout_secs}}`, then reference the tool by id from the
  agent. `expects_response: true` makes the agent wait for our `client_tool_result`. Timeout is
  1–120 s (default 20); we use 10.
- Webhook (server) tools call an HTTPS URL that ElevenLabs can reach, so they need a public
  endpoint or a tunnel. Client tools don't.
- Parameter schema: each property has a `type` and a `description`; arrays have `items`. The doc
  doesn't list the allowed literal types, so we use `integer` for table, seat and qty.
  Verified: tool creation accepted it and the agent sends ints.

### Text to speech (fixtures)
Docs: [create speech](https://elevenlabs.io/docs/api-reference/text-to-speech/convert)

- `POST /v1/text-to-speech/{voice_id}?output_format=pcm_16000` with
  `{"text", "model_id": "eleven_multilingual_v2"}` (the default model). It returns raw PCM.
  `JBFqnCBsd6RMkjVDRZzb` is the premade voice from the reference example; `ELEVENLABS_VOICE_ID`
  overrides it.

## Tool path

- **Winner: client tools over the conversation WebSocket, with the agent in text-only mode.**
  All six tools were created through the API, and the agent called them with the right arguments
  in every clean run. No public URL or tunnel is needed, so webhook tools and the separate-LLM
  fallback weren't built.
- In fixture 1 the agent split the utterance into two `add_item` calls. In fixture 2 it mapped
  "soup" to `Roasted Tomato Soup` and our code returned `not_found`. For "dessert" it sent
  `cancel_order(items=["dessert"])`, which the code turns into a course-level proposal.

## Guards (in `order.py`, tested in `tests/test_order.py`, no network)

- Dish names resolve by exact name or alias, ignoring case, hyphens and a leading "the".
  Anything else returns an error with the 3 closest menu names.
- Each alteration is checked against that dish's `allowed_alterations`. Allowed ones are applied.
  Others go in `flagged_alterations` with a warning in the result and are never applied.
- `confirm_order` / `cancel_order` only add a proposal and return `needs_confirmation`.
  `cancel_order` items can be dish names or a course ("dessert").
- `set_allergy` is pinned to the seat and survives later removals. It and `add_item` report
  conflicts with the menu allergens ("Scallop Crudo contains shellfish").
- Every argument is validated; numeric strings like "12" are accepted. `dispatch()` never raises:
  unknown tools, wrong types and internal errors all come back as `is_error` results.
- `remove_item` for a dish that isn't on the seat is now an **error result** naming what is on
  the seat ("seat 2 has no Roasted Tomato Soup (it has: Cedar Plank Salmon)"). This is the fix for
  the noise finding below ("no suit" -> the agent removed the salmon): enforced in code.
- Removals, cancels and confirms only add a pending proposal (with an id). `OrderBook.accept(id)`
  applies one (the server's tap), `reject(id)` drops it (swipe up). `fire()` (tap with nothing
  pending) refuses while anything is pending. A sent or cancelled table can't change.
- Cancelling a course that wasn't ordered is an error too. Fixture 1 now also orders the torte
  (seat 1) and the soup (seat 2), so fixtures 2 and 4 make pending proposals; after both taps the
  order matches the original voice test (s1 halibut no butter, s2 salmon no dill, s3 shellfish).

## Voice relay (`relay.py`)

`python relay.py` serves ws://localhost:8790/ws. The dev fake backend proxies the glasses'
capture.* / order.* messages to it. Per connection: capture.start opens a `ScribeStream` (VAD
commit, 0.8 s silence) and the agent (8 s start timeout) while buffering up to 5 s of audio;
committed segments go to the agent one turn at a time; every tool call is followed by an
order.draft (lines by seat, allergies, pending proposals, voice state, code-written notice for a
refused call). order.confirm / order.cancel_confirm / order.reject apply the server's gestures
and tell the agent with a `contextual_update`. A provider failure sets `voice: offline`, which
the glasses show as VOICE OFFLINE. Tests: `tests/test_relay.py` (fake STT and agent).

Sync 1: the real backend's hub (`backend/app/voice_bridge.py`) is now the relay's client, exactly like the
fake backend was; when a draft comes back `sent`, the hub writes its lines into its own order store and
fires it. The relay reads the one menu, `data/menu.json` (13 dishes; `backend/voice/menu.json` is gone), and
the fixtures speak table two, which is on `data/floor.json`.

## Latency (end of speech → first tool call)

Measured with `python run_spike.py --repeat 5 fixtures/0*.pcm` (5 fresh sessions × 4 fixtures).
"End of speech" is the send time of the last 100 ms frame above −40 dBFS. The end time is when the
`client_tool_call` arrives. Fixtures are streamed at real-time pace from a Devin VM. LLM is
`gemini-2.5-flash`, VAD silence 0.8 s.

| Run set | n | Median | Min | Max |
|---|---|---|---|---|
| clean TTS, 4 fixtures × 5 runs | 20 | **1.90 s** | 1.75 s | 2.22 s |
| white noise at 5 dB SNR (`make_fixtures.py --snr-db 5`), × 5 runs | 19 of 20 | 1.52 s* | 1.30 s | 2.67 s |

Per fixture (clean, median of 5): order 2.19 s, no soup 1.85 s, allergy 1.78 s, cancel dessert 1.88 s.

\* The noisy number reads too low. With constant noise above −40 dBFS, the "last loud frame" is the end
of the file, not the end of speech. Don't compare it with the clean number.

### Noise result (the real risk)
- Clean: all 5 runs ended in exactly the target order state.
- At 5 dB SNR, Scribe heard "Actually, no **suit** for seat two" in all 5 runs. In 4 of 5 the agent
  read that as removing seat 2's salmon, and the code allowed it because the salmon is a real item on
  that seat. In the 5th run no tool was called for that utterance. The other fixtures transcribed
  fine, apart from a stray `。`.
- Next steps to try: Scribe `keyterms` with the menu names; a code rule that `remove_item` must
  name a dish that actually appears in the utterance; and have removals show on the glasses as an
  undoable line rather than happen silently.

## HW-PENDING

- A real G2 mic stream through the same path. Frame size and format match on paper.
- Accuracy in restaurant / judging-hall noise. White noise is only a stand-in.

## Clip path (conversational capture)

Docs read 2026-10-18: [speech-to-text convert](https://elevenlabs.io/docs/api-reference/speech-to-text/convert)
(`POST /v1/speech-to-text`, multipart, `model_id=scribe_v2`, `file_format=pcm_s16le_16` for raw 16 kHz s16le
mono, `language_code`, `diarize`, `tag_audio_events`), and the realtime reference (query `language_code`).

- **English is pinned** in both Scribe paths (`language_code=en`): a real-G2 test transcribed bystanders and
  once switched to Turkish.
- `relay.py`: `capture.start{mode:"clip", table?}` buffers frames in memory (max 122 s), `capture.stop` runs
  `transcribe_clip` (one batch call, diarized; lines split at speaker changes and 0.6 s pauses), then one
  agent turn. The clip bytes are dropped once sent to Scribe; nothing is written to disk.
- Clip agent (`create_agent.py`, default): one client tool, `set_order(table?, items[{guest, seat?, dish, qty,
  alterations}], allergies[], unclear[], notes[])`. Nested object arrays were accepted by `POST /v1/convai/tools`.
- **Guards in `order.py` (tests in `tests/test_order.py`):** guests become seats in the order they ordered (a
  spoken seat wins); dishes menu-checked (unknown → code-written `?` line); disallowed alterations flagged;
  every dish, alteration and allergen must be words that were said in the clip; a guest with an unclear line
  gets no guessed dish; unclear lines or notes phrased as questions are dropped (the agent's text is never
  shown); allergies are never removed; a dish a later clip drops only becomes a removal proposal; the table
  is from the ORDER task (a spoken one can't override it) or spoken; send is refused without a table.

LLM choice (5 × `conv_task` + 1 table-less, real hub + relay, clip stop → draft, same day):

| llm | conv_task right | latency |
|---|---|---|
| gemini-2.5-flash | 3/5 | ~6.5 s |
| gemini-2.5-flash-lite | 0/5 (allergy seat, missing ? line, invented alterations) | ~2.0 s |
| gpt-4.1-mini | 3/5, one 20 s stall | ~2.5 s |
| **claude-haiku-4-5** | 4/5 | 3.9-4.2 s |

After the fixture was re-spoken with more small talk, haiku put both mains on seat 1 in 5/5; a worked example
in the prompt fixed seats (5/5) but the allergy still goes to s1 instead of s2 in 4/5. Next to try: distinct
guest voices (diarization), or an allergy `?` line when the speaker is ambiguous. CREAO is not used here (runs
take minutes); a CREAO end-of-shift digest could come later.

### Summary and answers (branch `devin/clip-summary`)

- A second agent (`create_agent.py --mode talk`, `.talk_agent_id`, claude-haiku-4-5) reads the same
  transcript in parallel with the order agent and calls `set_talk(summary, questions[{guest?, seat?, q,
  kind, dish?, allergen?, change?, reply?}])`. The relay sends the order draft as soon as `set_order`
  lands and the summary and answers in a second `order.draft` when `set_talk` lands; a talk failure leaves
  the order card as it was (no conversation lines).
- **The menu answers, not the agent (`answers.py`, `tests/test_answers.py`):** for an allergen, dietary or
  alteration question the agent only names the dish/allergen/change; code writes the reply from
  `data/menu.json` (`allergens`, `allowed_alterations`). A reply the agent wrote is only kept for a comment
  ("we're in a rush") and is dropped if it names a dish or allergen. Anything the menu can't answer
  (vegetarian, spicy, gluten-free bread) becomes `known: false`, `a: "not in menu data"`. Max 4 answers.
- One combined agent was slower (old main 3.83 s → 5.33-6.29 s to the order), hence two agents.

Latency, relay bench (`capture.start{mode:"clip"}` + frames + `capture.stop` over the local socket; median
of 5; same relay, same agents):

| Fixture | Scribe batch | → order draft | → summary + answers |
|---|---|---|---|
| 60 s (`conv_questions`, old main, order only) | | 3.83 s | – |
| 60 s (`conv_questions`) | 1.69 s | 3.83 s | 4.62 s |
| **120 s (`conv_2min`)** | **2.51 s** | **4.13 s** | **5.05 s** |

### 2-minute clip (owner, 2026-10-18; branch `devin/clip-2min`)


- `conv_2min` (120.0 s, 3.84 MB): 17.8 s of small talk from `conv_task`, then `conv_answers_only`,
  `conv_questions`, `conv_table_last`; 33 turns, 327 words.
- **Batch Scribe accepted the 120 s raw PCM** (`scribe_v2`, `pcm_s16le_16`, diarized) 5/5: 2.23, 2.98, 2.51,
  2.54, 2.43 s (60 s: 1.22-1.85 s). The transcript is ~330 words, far inside the agent's context.
- Cost of 2 minutes: Scribe +0.8 s, order +0.3 s, summary/answers +0.4 s (table above); WebView memory 3.84 MB
  of preallocated frame slots (was 1.92 MB). In the simulator against the real hub the gap is bigger, median
  of 5 swipe → order 3.75 s (60 s) vs **5.46 s** (120 s), → summary and answers 4.82 s vs **6.70 s**
  (`glasses/NOTES.md`): noticeably slower than the ~4 s bar.
- A 2-minute clip holds more of the meal, so a later swipe re-reads lines already in the draft (the existing
  "a dish a later clip drops only becomes a removal proposal" rule covers it).

### Table by voice

- `tables_said()` (`commands.py`) finds every "table N" in the clip transcript (digits or words; "number"
  allowed in between); the relay binds the last floor table said, so "thanks, that was table four" as the
  server's last words binds T4 (`conv_table_last`: 15.1 s, no ORDER task → T4, checked against the live
  relay). In a clip, homophones ("table for two") don't count. It never overrides the ORDER task.
- `verity table N` (command stream; `four`/`for`/`4` all parse to 4 after the wake word) rebinds the unsent
  draft over the task's table, checked against `data/floor.json` (T1-T8): `no table 12`, `already sent`
  after the tap, `no order to set the table for` with no draft (`tests/test_relay.py`).
- Noise test, one run with "Verity, table four.": recognised as table 4 in **4/4** conditions (clean,
  babble -12 dB, babble -12 dB + white 10 dB, babble -6 dB). Whole word list: 43/68; false triggers 0
  (conv_task, conv_task + noise, near misses incl. "Could we get a table for two by the window?").

## Voice commands (`commands.py`, relay command stream)

"verity" + one of up / down / back / confirm / clip / accept / decline / done / handoff [Name] /
nevermind / revert / menu (or controls) / queue / table N. A fixed word list, no LLM: an intent only counts when it directly follows the wake word, so "we're done here" or "I accept"
in conversation never fires. While the Server role is on, the glasses stream the live mic to the relay
as `capture.start {mode: "command"}`; the relay runs realtime Scribe (English, VAD commit 0.8 s) and
sends back only `voice.command {intent}`. The transcript is never logged, stored or forwarded. While a
clip uploads, frames go to the clip; after it, back to the command stream (the hub keeps a separate
per-socket command capture with no table).

Unknown words right after "verity" (at most 5; longer is ordinary speech and ignored) go to Gemini
(`gemini_intent.py`, `GEMINI_API_KEY`, the router's `FS_GEMINI_MODEL`, default `gemini-3.1-flash-lite`,
`FS_INTENT_TIMEOUT_SEC` timeout, default 2 s, structured JSON)
with only that short phrase. Code checks the answer is one of the fixed intents and a handoff name is
one plain word; anything else, a timeout or no key becomes `voice.unknown {words, reason?}` and the
glasses show `Didn't get: <words>`. Before the Gemini call the relay sends `voice.mapping {words}`, so the
glasses show `Verity: processing...` while it waits. Realtime Scribe wrote the TTS "verity queue" as "Verity Q" (2/2 in
the simulator run), so `q`/`cue` count as queue after the wake word.

### Gemini intent call: why it was slow, and what changed

Boyuan measured the relay's call with the real key: `gemini-2.5-flash-lite` (the old default) returned 404;
`gemini-3.1-flash-lite` answered in 3.2 / 4.5 / 8.8 s against a 3 s timeout. The router
(`backend/app/router.py`) gets 0.5-0.8 s from the same key. Request bodies compared:

| | relay before | router | relay now |
|---|---|---|---|
| model | `GEMINI_MODEL`, default `gemini-2.5-flash-lite` | `FS_GEMINI_MODEL`, default `gemini-3.1-flash-lite` | `FS_GEMINI_MODEL`, same default |
| key | `x-goog-api-key` header (AQ. keys 404) | `?key=` | `?key=` |
| prompt | one user turn, ~1 KB with the words interpolated | fixed `systemInstruction` + JSON context | fixed `systemInstruction` + only the words as the user turn |
| output | JSON object schema (`intent` enum + `name`) | `text/x.enum` | JSON object schema (the handoff name needs a field) |
| thinking | model default | model default | `thinkingLevel: MINIMAL` |
| timeout | 3 s, fixed | `FS_ROUTER_TIMEOUT_SEC` 3 s | `FS_INTENT_TIMEOUT_SEC`, default 2 s |

Google's docs say `minimal` is already 3.1 Flash-Lite's default thinking level
(https://ai.google.dev/gemini-api/docs/gemini-3), so asking for it explicitly should change little. Prompt
size is ~1.1 KB either way. Without the key here, the biggest suspect is the JSON object schema versus the
router's plain enum. `gemini_latency.py` times 5 calls of the old body against the new one (same model,
same `?key=`) and prints prompt and thinking tokens per call; the key is never printed.

Before/after, 5 calls each: **not measured yet** (no `GEMINI_API_KEY` in this environment). Run
`GEMINI_API_KEY=... .venv/bin/python gemini_latency.py` and fill this in. If "after" is still above 1.5 s,
the next step is the router's `text/x.enum` with the handoff name read from the words in code.

### Noise test (`noise_test.py`, Scribe batch, TTS "Verity, <command>." in the server voice)

Babble = the 59 s table conversation fixture mixed under the command; white noise added with
`make_fixtures.add_noise`.

| Condition | Recognised |
|---|---|
| clean | 7/8 |
| babble -12 dB | 6/8 |
| babble -12 dB + white noise 10 dB SNR | 6/8 |
| babble -6 dB | 7/8 |
| **overall** | **26/32 (81%)** |

- Misses were the babble's words landing first (transcript starts "Hmm", "doing", "take"), not
  misspellings of the wake word. Scribe wrote "verity" correctly every time it heard it (22/22 first
  words); no "verita" / "very tea" variants were needed.
- Inflections Scribe produced in a first run ("Verity accepts", "Verity clipped", "Verity confirmed")
  are matched; "upped"/"downs" are not.
- An earlier run with babble at 0 dB (as loud as the command) got 1/8: a guest talking over the server
  at the same level wins. Real speech at the glasses mic should be much closer than the table.
- **False triggers: 0** on the 59 s conversation with no commands, 0 on the same with 5 dB white noise,
  0 on near misses ("very tasty", "verify the bill", "Verity is my sister's name", "we're done, I accept,
  let's go back up").

### Realtime Scribe (the path the relay uses), same fixtures, clean

15/16 before, 16/16 after: realtime wrote "Verity, done." as "Verity Dunn." both times (a surname after
a first name), so `dunn`/`dun` map to done. Everything else came back verbatim.

### Crowd: realtime noise test (branch `devin/voice-crowd`, `noise_test.py`)

Realtime Scribe, streamed in 100 ms frames like the relay. 14 TTS "Verity, <command>." in a near voice
(active speech -20 dBFS), 4 s apart, over 4 far talkers (babble from other TTS voices, low-pass +
early reflections), level is babble vs command. Each column is 2 runs (28 commands) unless noted.
`soundalikes` parser on in "after". Defaults now: `VOICE_CMD_GATE_DBFS=-22`, `VOICE_CMD_GATE_HOLD=3`,
`VOICE_CMD_VAD_THRESHOLD=0.6`, `VOICE_CMD_KEYTERMS=on`, `VOICE_CMD_FILTER_BG=on` (each `off` to disable).

| Babble level | before (main) | keyterms + gate -22 + VAD 0.6 | + filter_background (now default) |
|---|---|---|---|
| clean | 28/28 | 28/28 | 28/28 |
| -12 dB | 3/28 | 28/28 | 28/28 |
| -6 dB | 2/28 | 28/28 | 28/28 |
| -3 dB | 2/28 | 14/28 | 21/28 |
| 0 dB | 0/28 | 0/28 | 2/28 |
| +3 dB | 0/28 | 0/28 | 0/28 |

- Why main fails in realtime: with babble running Scribe's VAD never sees silence, so it doesn't commit
  until the babble pauses, and the commit mixes in other people's words. The gate turns everything
  under -22 dBFS into digital silence, so the VAD commits right after the wearer stops.
- Sweep (1 run, 14 per level, keyterms on): gate -24: -6 dB 12/14, -3 dB 2/14; -22: 14/14, 8/14;
  -20: clean drops to 11/14 (it clips quiet syllables). VAD 0.6 alone: -12 dB 2/14 (no help); with the
  gate it's neutral, kept because the brief asked for it. Keyterms alone: no change (the problem is the
  commit, not the words).
- **False triggers: 0** in every run, before and after: 59 s conversation, near misses, babble alone at
  -12/-6/-3/0/+3 dB. With the gate, realtime committed "Verity is my sister's name" as its own segment,
  which went to Gemini as an unknown; `ABOUT_VERITY` ("is", "was", "said", ...) now drops it.
- 0 dB and louder still fail: when a talker a metre away is as loud at the mic as the wearer, a level
  gate can't separate them. HW-PENDING: the -22 dBFS gate is relative to our TTS level; it needs
  checking against real G2 mic levels (wearer vs a guest at 1 m) in a loud room.

End of command → `voice.command` (Heard), through `RelaySession`, 5 commands (`noise_test.py --latency`):

| | before | gate, VAD 0.6, keyterms | + filter_background (default) |
|---|---|---|---|
| clean | 0.97, 1.03, 0.99, 0.82, 1.12 → **0.99 s** | 0.93, 0.84, 0.88, 0.94, 1.15 → **0.93 s** | 1.20, 1.12, 0.94, 0.95, 1.18 → **1.12 s** |
| babble -12 dB | none heard (0/5) | 1.13, 0.87, 0.87, 1.07, 1.29 → **1.07 s** | 1.15, 1.00, 1.03, 1.02, 1.25 → **1.03 s** |

filter_background costs about 0.1 s clean (one set of 5); it buys -3 dB 14/28 → 21/28. `VOICE_CMD_FILTER_BG=off`
gives that back if the room turns out quieter.

### Sound-alikes (`commands.py`)

After an exact "verity", the next word may be a listed sound-alike (`SOUNDALIKES`, each with its reason:
except→accept, conform→confirm, click/clear→clip, dunne→done, queued→queue) or one edit from a command
of 5+ letters. Wake-word sound-alikes (`WAKE_SOUNDALIKES`: verily, variety, verety, varity) only count
at the start of a sentence and must be followed by an exact command; `NOT_WAKE` (verify, very, rarity,
clarity, ...) never counts. Negative tests in `tests/test_commands.py`.

### Order clips: diarization (`voice_session.transcribe_clip`, `clip_test.py`)

Batch Scribe with `diarize=true` and keyterms; the agent gets `speaker_N: ...` lines. Each speaker's
level is the median dBFS of 50 ms frames over their words. Reference = the loudest speaker, or the
second loudest if the loudest (the wearer, at the mic) is 6+ dB above it. Speakers more than
`VOICE_CLIP_QUIET_DB` (6) below it, or 3+ dB below with under 20% of the top speaker's words, are dropped
as another table. Test: `tests/test_relay.py` two-table fixture (no network).

Live (`clip_test.py`, 20 s clip: wearer + 4 guests ordering 5 dishes, a second table 10 dB quieter and
"far" ordering duck/ribeye/risotto/pork belly), 5 runs each:

| | leaks (runs with a neighbour dish) | our dishes kept | batch Scribe median | clip stop → draft median |
|---|---|---|---|---|
| before, wearer = guests | 5/5 | 15/15 | 1.14 s | 3.29 s |
| after, wearer = guests | 0/5 | 12/15 (1 run: Scribe returned a garbage 1-word transcript) | 1.07 s | 3.00 s |
| before, wearer +12 dB | 5/5 | 15/15 | 1.39 s | 3.99 s |
| after, wearer +12 dB | 0/5 | 15/15 | 1.33 s | 3.13 s |
| neighbours only 6 dB quieter, after | 5/5 | 15/15 | 1.21 s | 3.60 s |

- Diarize adds no measurable latency (batch medians within run-to-run noise).
- 2 of ~30 keyterm runs came back as a 1-word garbage transcript; a repeat of 8 calls each with no /
  batch / realtime keyterms gave 0 garbage, so it's intermittent, not keyterms. HW-PENDING to watch.
- A neighbour only 6 dB quieter still leaks: the level rule can't tell them from a soft-spoken guest.
  HW-PENDING: real speaker levels at a table vs the next table.

### Simulator against the real backend (`?say=` debug path)

End of the spoken command → `voice.command` on the glasses: 0.92, 0.62, 0.61, 0.61, 0.61 s, **median
0.61 s** (Scribe's 0.8 s VAD silence is most of it). accept → `Heard: accept` → task accepted 3 s later;
decline on the accepted task → `Can't decline: already accepted`; done → task done.

### HW-PENDING
- Recognition with a real voice at the glasses mic in a loud room, and false triggers over a real shift.
- Phone-link bandwidth/battery of streaming the mic continuously (on top of the rolling buffer).
- Scribe realtime session limits for an always-open stream (reconnects are handled; long-session
  behaviour not measured).
