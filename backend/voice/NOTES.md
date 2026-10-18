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
- `keyterms` (biasing toward dish names) exists, but the docs don't show how an array is encoded
  in the query string. Not used yet. TO-VERIFY before relying on it for rare dish names.

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
- `relay.py`: `capture.start{mode:"clip", table?}` buffers frames in memory (max 62 s), `capture.stop` runs
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

## Voice commands (`commands.py`, relay command stream)

"verity" + one of up / down / back / confirm / clip / accept / decline / done / handoff [Name] /
nevermind / revert / menu (or controls) / queue. A fixed word list, no LLM: an intent only counts when it directly follows the wake word, so "we're done here" or "I accept"
in conversation never fires. While the Server role is on, the glasses stream the live mic to the relay
as `capture.start {mode: "command"}`; the relay runs realtime Scribe (English, VAD commit 0.8 s) and
sends back only `voice.command {intent}`. The transcript is never logged, stored or forwarded. While a
clip uploads, frames go to the clip; after it, back to the command stream (the hub keeps a separate
per-socket command capture with no table).

Unknown words right after "verity" (at most 5; longer is ordinary speech and ignored) go to Gemini
(`gemini_intent.py`, `GEMINI_API_KEY`, default `gemini-2.5-flash-lite`, 3 s timeout, structured JSON)
with only that short phrase. Code checks the answer is one of the fixed intents and a handoff name is
one plain word; anything else, a timeout or no key becomes `voice.unknown {words, reason?}` and the
glasses show `Didn't get: <words>`. Realtime Scribe wrote the TTS "verity queue" as "Verity Q" (2/2 in
the simulator run), so `q`/`cue` count as queue after the wake word.

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

### Simulator against the real backend (`?say=` debug path)

End of the spoken command → `voice.command` on the glasses: 0.92, 0.62, 0.61, 0.61, 0.61 s, **median
0.61 s** (Scribe's 0.8 s VAD silence is most of it). accept → `Heard: accept` → task accepted 3 s later;
decline on the accepted task → `Can't decline: already accepted`; done → task done.

### HW-PENDING
- Recognition with a real voice at the glasses mic in a loud room, and false triggers over a real shift.
- Phone-link bandwidth/battery of streaming the mic continuously (on top of the rolling buffer).
- Scribe realtime session limits for an always-open stream (reconnects are handled; long-session
  behaviour not measured).
