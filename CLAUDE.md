# Glossary (LA Hacks, Oct 17-18 2026)

Even Realities G2 app for new hires: the glasses listen to a meeting and show a short definition card when
someone says company jargon the wearer hasn't learned. A phone companion runs a Gemini agent that proposes
terms from the company's docs; a human approves every term before it reaches the glasses.

The full brief (spec, sponsors, rules, architecture, lessons) is the **`glossary-brief` skill** in
`.claude/skills/glossary-brief/`. Read the relevant file before designing or changing anything.

- **Team / owners:** [names; who owns glasses / server / companion / design]
- **Code freeze:** [deadline from check-in]. Record the demo video and deploy *before* it.

## Event rules (breaking these = disqualification)

- All code, data (the fictional company, its docs, the term list, the demo script) and designs are created in
  this repo during the event. Never search this machine for earlier projects or copy from them. Public SDKs,
  Even's templates, npm packages and Even's Claude Code plugin skills are fine.
- List every framework and library used in `README.md`.
- Keep `AI_USAGE.md` current: how Claude Code builds this, and how Gemini is used in the product. It gets pasted
  into Devpost; MLH disqualifies uncredited AI use.
- Fictional data only. Record only people who agreed. Never store audio.

## Commits

The git history is our evidence that the work happened at the event. Many small commits beat a few big ones.

- **Commit after every logical change that works** (builds, runs, or passes its check). One concern per commit.
  Never sit on more than ~30 minutes of uncommitted work.
- **Commit straight to `main`.** Use a short-lived branch only for a risky experiment (e.g. swapping the
  speech-to-text provider), and merge it without squashing: the granular history is the evidence.
- **Message format:** Conventional Commits, imperative, subject ≤ 72 chars, no trailing period.
  `type(scope): what changed`
  - types: `feat` `fix` `perf` `refactor` `test` `docs` `chore`
  - scopes: `glasses` `server` `companion` `agent` `data` `demo` `infra`
  - e.g. `feat(server): hold back cards within 30 s of the last one`
- **Body** (when useful) says *why*, not what. For perf/latency changes put the before/after numbers in the body;
  they feed the Sentry write-up (`p95 per frame 51 ms -> 1.3 ms`).
- Commits made by Claude Code keep their `Co-Authored-By: Claude` trailer. It is part of the AI-use disclosure.
- **Stage explicit paths** (`git add server/src/matcher.ts`), not `git add -A` / `git add .`. Read
  `git diff --cached` before committing.
- **Secret check before every commit.** Both commands must print nothing; read every hit before overriding:
  ```sh
  git diff --cached --name-only | grep -E '(^|/)\.env' | grep -v '\.env\.example$'
  git diff --cached -U0 | grep -nE 'AIza[0-9A-Za-z_-]{35}|sk_[0-9a-f]{32,}|sntrys_|tskey-|[0-9a-f]{40}|PRIVATE KEY'
  ```
  If a key ever lands in a commit or a chat, rotate it. Rewriting history doesn't help once it has been pushed.
- **Never commit:** env files (only `.env.example`, with names and no values), `*.ehpk`, `dist/`, `node_modules/`,
  audio recordings, or the runtime store (approved terms, learned ids, recaps).
- **Don't push unless asked.** When pushing: `git pull --rebase` first, never force-push `main`, never
  `--no-verify`, never amend a pushed commit.

## How we work

- Follow the order in `07-FIRST-HOURS-CHECKLIST.md`. The card loop on a real G2 comes before everything else.
- When a step needs a human (Even Hub upload, phone install, pairing, recordings, accounts), give numbered steps
  with the exact commands, then wait. Ask before spending money, creating cloud servers or buying a domain.
- Don't call anything done until you've seen it work (a test, a screenshot, or on the glasses). Write the numbers
  in `NOTES.md`.
- Log HW-PENDING answers, surprises and your own mistakes in `NOTES.md` as they happen.
- Put rules in code, not prompts: the approval gate, quote checks, card limits, no LLM in the card path.
- Versions, model IDs and numbers in the brief were true when tested. Check current docs before relying on them.
- API keys stay on the server: never in the WebView bundle, logs, commits or chat.
