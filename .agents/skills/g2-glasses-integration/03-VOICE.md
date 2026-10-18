# 03. Voice order capture

## The flow

(Since conversational capture, see `AGENTS.md`: the mic keeps a rolling minute and a swipe back sends it as one
clip, transcribed in one batch call.) Original flow: server swipes down → the glasses app starts streaming mic PCM to our backend → backend streams it to ElevenLabs
Scribe (realtime speech-to-text) → each committed transcript segment goes to an ElevenLabs agent in text-only
mode → the agent calls our order tools → the backend validates and applies them → the glasses card shows the
order by seat, updated in place. Sending the order to the kitchen or cancelling it needs a tap.

Read the current ElevenLabs docs (Scribe realtime, Agents tools, text-only/chat mode) before coding; model IDs,
endpoints and message shapes change. If the agent can't call tools in text-only mode, keep Scribe for speech and
send transcripts to any tool-calling LLM instead. Record which path worked in `backend/voice/NOTES.md`.

## Order tools

- `add_item(table, seat, dish, qty, alterations[])`, `remove_item(table, seat, dish)`,
  `modify_item(table, seat, dish, change)`, `set_allergy(table, seat, allergen)`
- `confirm_order(table)` and `cancel_order(table, items?)` only **propose**. They return
  `{"status": "needs_confirmation"}`; the server's tap does the real action.

## Rules enforced in code, not in the prompt

- **Verify, don't prompt.** A prompt rule was ignored 3 times out of 5 in earlier testing; a code guard was
  reliable. Keep guards narrow and read what they match.
- A dish not on the menu returns an error with the closest menu names ("did you mean...").
- An alteration not in that dish's `allowed_alterations` is flagged on the card, never silently applied.
- Allergies are pinned to the top line and never dropped by a later edit.
- **Validate every tool argument.** Tool errors go back to the agent as tool results; one malformed call once
  crashed a whole agent session.
- Tell the agent in its prompt what it can't do (fire or cancel an order), or it will claim it did.
- Return every tool call to the UI or log so the steps are visible.
- No LLM call in the card path: showing or updating a task card never waits on a model.

## Speech-to-text lessons

- **Close streams properly:** send the close message, send about 2 s of trailing silence, and keep the socket
  open until the provider closes it. Otherwise the last sentences are lost (one benchmark scored 3/10 for this).
- **Noise cliff:** on synthetic voices with another STT provider, recognition went from 10/10 in quiet to 7/10
  at about +2 dB SNR to **nothing** at 0 dB or below. A restaurant or a judging hall can be that loud. Measure
  ElevenLabs on noisy audio, not just clean audio, and keep the text-injection backup.
- Rare words get misspelled ("chiffonade" → "chaffonade"). Match dish names with aliases and fuzzy matching
  (edit distance, sound-alike codes) against the menu, then confirm on the card.
- If the stream closes mid-order, reopen it with backoff; don't leave the session silently deaf.
- Keep speech-to-text behind one small interface so the provider is a one-file change.

## Latency and reliability

- Measure end of speech → tool call → card update. Report the median of at least 5 runs in `NOTES.md`.
- Every external call has a timeout and a visible failure state on the glasses ("voice offline, tap to retry").
- If a call stalls, a second attempt in parallel after a short delay (hedging) cut stall times a lot with other
  providers. Use it only if latency numbers show stalls.

## Privacy

The mic records into a rolling 60 s buffer in WebView memory while the Server role is on; older audio is dropped
continuously and only a clipped minute leaves the device, on a swipe back. The backend transcribes it and keeps
nothing of the audio or transcript afterwards. Never stored or committed.
Observability tools never receive audio, transcripts or prompts.
