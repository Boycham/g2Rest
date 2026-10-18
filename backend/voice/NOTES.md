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
