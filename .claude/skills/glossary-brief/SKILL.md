---
name: glossary-brief
description: Build brief for Glossary, the Even Realities G2 jargon-card app for new hires (LA Hacks, Oct 17-18 2026). Product spec, gesture map, card rules, sponsor track requirements (Even Realities, Workday, Sentry, Gemini, ElevenLabs, Paper), LA Hacks / MLH rule 2 integrity rules, architecture, G2 SDK / Even Hub / Deepgram / Gemini / Sentry gotchas, the fictional jargon-pack data, the first-hours checklist, the demo plan and fallbacks. Use before designing, building or changing any part of Glossary (glasses app, server, term matcher, card rules, speech-to-text, Gemini agent, recap, companion review screen, Sentry, demo, README, Devpost), and whenever a G2 SDK, Even Hub packaging, event-rule or sponsor-requirement question comes up.
---

# Glossary: brief for the build agent (LA Hacks, Oct 17-18 2026)

This skill is everything a coding agent needs to know, other than code, to build **Glossary** during LA Hacks.
It holds the product decisions, the sponsor requirements, the event rules, the architecture, and the lessons the
team already paid for. It contains no code, no keys and no design files. Build everything at the event.

## What Glossary is, in one paragraph

Glossary is an Even Realities G2 app for new hires. The glasses listen to a meeting. When someone says a
piece of company jargon the wearer hasn't learned yet, a short definition card appears in their line of
sight, then gets out of the way. A phone companion app has an AI agent that reads the company's documents,
proposes a jargon list with sources, and the new hire approves, edits or rejects every term before it can
reach the glasses. If the wearer gets lost, they swipe down and get a three-line "what did I miss" recap
when the conversation goes quiet.

## Reference files

At kickoff, read all of them in this order. After that, read the file for the area you're about to touch
before designing or changing it.

| File | What it settles | Mistakes it prevents |
|---|---|---|
| [01-PRODUCT-SPEC.md](01-PRODUCT-SPEC.md) | Gestures, card rules, companion screens, pitch answers | A gesture map Even's review rejects; a noisy, unoriginal jargon explainer |
| [02-SPONSORS.md](02-SPONSORS.md) | Which tracks we enter and each one's hard requirements | Missing a pass/fail requirement; stacking tracks we can't win |
| [03-RULES-AND-INTEGRITY.md](03-RULES-AND-INTEGRITY.md) | Event and MLH rules, what rule 2 means, what to disclose | Disqualification for pre-existing work or uncredited AI use |
| [04-ARCHITECTURE.md](04-ARCHITECTURE.md) | Components, data flow, term matching, data model, hosting | An LLM in the card path; a host whose URL changes; keys in the WebView |
| [05-LESSONS.md](05-LESSONS.md) | SDK, speech-to-text, Gemini, Sentry, Paper and testing facts | Hours lost to known gotchas |
| [06-JARGON-PACK-AND-DATA.md](06-JARGON-PACK-AND-DATA.md) | The fictional company, source docs, term format, the agent's job | Real data; an agent that invents definitions |
| [07-FIRST-HOURS-CHECKLIST.md](07-FIRST-HOURS-CHECKLIST.md) | Timed plan from check-in to a working core loop | Finding the G2 / Beta blocker at the end |
| [08-DEMO-PLAN.md](08-DEMO-PLAN.md) | The judged demo, the video, backups, Devpost | A dead demo in a loud hall; an incomplete submission |
| [09-RISKS-AND-FALLBACKS.md](09-RISKS-AND-FALLBACKS.md) | What can break, what is unproven, what to cut | Spending the last hours on extras |
| [BUILD-PROMPT.md](BUILD-PROMPT.md) | The kickoff prompt to paste into Claude Code after hacking starts | |

## Ground rules for the agent

- **Build in a repo created after hacking starts.** Write all code, data and designs at the event.
  See [03-RULES-AND-INTEGRITY.md](03-RULES-AND-INTEGRITY.md).
- **This skill is the only prior material to use.** Do not search the machine for earlier practice code,
  and do not copy or paste from any. Public SDKs, templates, npm packages and sponsor tools are fine.
- **Lessons are past observations, not limits.** Earlier quota, network and tool problems may not recur, and earlier workarounds may not be needed. Use the event's real accounts, hosts and current SDK behaviour.
- **Treat every fact here as "true when tested", not as permanent.** Model names, SDK versions, quotas and
  prices change. Verify against the current docs before relying on a number.
- **Everything about real G2 hardware is unproven.** All earlier testing ran on the desktop simulator. Items
  marked **HW-PENDING** must be checked on a borrowed G2 in the first hour.
- **Commits and secrets follow the repo's `CLAUDE.md`.** Commit after every logical change: the git history is
  the evidence that the work was done at the event. Secrets live only in gitignored env files.
- **Put rules in code, not in prompts.** Anything the model must never do (approve its own terms, invent a
  definition, put an LLM in the card path) is enforced by the server.
