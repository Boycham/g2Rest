# 05. Risks and process lessons

## Risks

| Risk | Fallback |
|---|---|
| No G2 early, or the Beta install fails | Developer Mode private build meanwhile; ask Even staff early. Even requires a physical G2 at judging. |
| App auto-rejected at review | Double tap exits via `shutDownPageContainer(1)`; whitelist exactly the hosts called; name ≤ 20 chars without "Even"; no banned category. |
| Too loud for speech-to-text | Text injection and a pre-recorded PCM order as demo backups; speak close to the glasses; measure in noise. |
| Agent mishears or invents a dish | Menu guard with "did you mean", alteration guard, tap to confirm. |
| ElevenLabs stalls or errors | Timeouts, visible failure state, retry; the task cards never depend on it. |
| Backend URL changes | Stable host from the start; never a quick tunnel for the Beta build. |
| Simulator stops delivering gestures | Restart it after every app or backend restart. |
| A key leaks into git or chat | Gitignored env files; secret grep before each commit; flag it in the PR so it gets rotated. |
| Running out of time | Server task card on the real G2 first, then voice orders, then the manager HUD. Everything else is optional. |

## Process mistakes not to repeat

- Confirm hardware and accounts exist before planning tests that depend on them.
- `mkdir -p` a log directory before redirecting into it. GNU `timeout` isn't on macOS. If `sleep` is blocked,
  poll a done-file with a time limit, not an iteration count.
- Wait for the health endpoint before tests. Reset state before each end-to-end run.
- Grep the route table before calling an endpoint, and check the API spec before saying a capability is missing.
- Log caught errors locally too, not only to an observability tool.
- Pick ports up front; 3000 is often taken.
- Click through any web UI in a real browser (a headless Chrome works) before calling a screen done.

## Sentry (if used)

- Start a new trace per glasses session, or every session's logs land in one trace.
- Never send audio, transcripts or prompts.
- A real story from practice: concatenating the whole audio buffer on every 100 ms frame blocked the event loop
  (51 ms spans); a fixed ring buffer fixed it (p95 per frame 1.27 ms → about 0). Look for the same pattern in the
  voice path.
