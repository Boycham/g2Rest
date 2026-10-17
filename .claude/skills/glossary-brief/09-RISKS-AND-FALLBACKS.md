# 09. Risks and fallbacks

## Never proven before the event

- Anything on a real G2: Beta install, gestures, the exit dialog, font fit, flicker, mic quality, lifecycle,
  SDK storage persistence, the wearer-vs-others loudness ratio.
- Real human voices in crowd noise (all speech numbers were synthetic or injected).
- ElevenLabs Scribe vs Deepgram on jargon in noise.
- A recorded human clip played through the full pipeline as a demo.
- The phone as a second microphone.
- The end-to-end card latency under a live mic after the audio-buffer fix.

## Risk table

| Risk | Likelihood | Impact | Mitigation / fallback |
|---|---|---|---|
| Can't get a loaner G2 early, or Beta install fails | Medium | Fatal for the Even track | Go to the Even table at T+0. Developer Mode private build as the interim path. Ask Even staff early about upload or review delays. |
| App auto-rejected at review | Low if rules followed | High | Double tap always exits via the system dialog; network whitelist lists exactly the hosts called; name ≤ 20 chars without "Even"; no banned category. |
| Hall too loud for speech-to-text | High | High | Consider the recorded-clip demo as the main path and live speech as the bonus; phone as a second mic held near the speaker (if built); have the wearer say the jargon (the loudest voice the glasses hear); ask early for a quieter judging spot; keyterms plus Gemini-generated aliases; sound-alike matching; text-injection backup. Expect missed cards, not wrong ones (confidence floor 0.6). |
| Terms misheard by speech-to-text, so no card | High in noise | High | Gemini-generated aliases at pack build; sound-alike matching (Double Metaphone + edit distance). Not a trained model. Measure plain vs aliases vs sound-alike on the noise set. |
| Sound-alike or embedding matching adds wrong cards | Medium | Medium | Tight thresholds, stricter for short terms; embeddings only as an extra signal; count false cards in the benchmark. |
| Gemini 503/429 or stalls | High | Medium | Lite models first, timeouts, fallback chain, hedging; nothing on the card path depends on Gemini; cached agent output for the demo. |
| Free-tier quota exhausted mid-event | Medium | Medium | Lock the API behind a token; don't expose the agent endpoint; keep a second key ready. |
| Server host URL changes | Low with a fixed host | High (forces repack + re-upload) | Use a stable host from the start; never a quick tunnel for the Beta build. |
| Laptop host sleeps or loses network | Medium | High | Keep the laptop awake and plugged in; phone hotspot as backup network (it worked). |
| Speaker labels mislabel the wearer | High | Medium | Loudness-based detection with calibration; diarization only as fallback; learning by gesture always works. |
| Everyday-word aliases cause card spam | Medium | Medium | Forbid them in the agent's extraction; human review; multi-word context aliases. |
| Agent invents or misattributes definitions | Medium | High for Workday | Quote verification in code, "not sure" flag, deferral guard, human approval. |
| Simulator stops delivering gestures | High after server restarts | Low (testing only) | Restart the simulator after every server restart. |
| A key leaks into git or chat | Low | High | Env files gitignored; grep staged files for key patterns before commit; rotate on any leak. |
| Rule 2 challenge | Low if followed | Fatal | Fresh repo at the event, frequent commits, no copied code, Devpost disclosure, organizer's written answer. |
| Running out of time | Medium | High | Core loop on the G2 first; companion review second; everything else is optional. Code freeze and video before the deadline. |

## What to cut, in order, if time runs short

1. Live view and history screens.
2. Chat configuration.
3. ElevenLabs (keep Deepgram).
4. Paper track polish (unless someone owns it).
5. Auto-learn from speech (keep learning by gesture).

Never cut: the card loop on the real G2, the Beta build, the approve/edit/reject review with sources, the
"I'm lost" recap, Sentry tracing + logs + replay, the README and the video.
