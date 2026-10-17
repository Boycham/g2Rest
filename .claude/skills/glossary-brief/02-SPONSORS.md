# 02. Sponsor tracks

**Team decision:** only enter tracks the product genuinely uses, meeting every requirement, with a real chance
to win. No sponsor stacking.

| Track | Enter? |
|---|---|
| Even Realities (core) | Yes |
| Workday (core) | Yes |
| Sentry (add-on) | Yes |
| MLH Best Use of Gemini API | Yes |
| MLH Best Use of ElevenLabs | **yes** ElevenLabs Scribe is the live speech-to-text |
| Paper, Best Designed Hack (add-on) | **yes** one teammate owns design (companion + G2 cards) all weekend |

**Dropped, and why:** Photon (a side feature next to entries that are iMessage-native), CREAO (its agent would
not be essential; the glasses work without it), Devin (single prize for the best Devin build), Vultr and GoDaddy
(hosting or a domain alone won't win "best use"), Fetch.ai (whole workflow must live in its chat with no custom
frontend), Base44 (must be built on Base44), veri (fine-tuning cost), and Visa, QuickBooks, Solana (financial,
which Even Hub bans), Espressif (hardware). Check at the event whether Devpost limits how many tracks one
project may enter.

## Even Realities (core): 4× G2 for 1st place

**Hard requirements (all pass/fail):**
- Package and upload the app to Even Hub as a **Beta build**.
- It must **run on a physical G2 during judging** (loaners at the Even table).
- Select the Even challenge on Devpost and include the Even Hub app name.
- App name ≤ 20 characters and must not contain "Even". "Glossary" works.
- Demo video showing the G2 experience (through-the-lens footage or the simulator is fine).
- README with install-and-run steps on G2, including every account and API key a tester needs.
- No medical, financial or emergency-routing apps.

**Judged on:** Made for G2, Quiet by Design, Originality, Experience & Polish, Execution ("can a judge put on
G2 and experience the core idea right now?").

**How we meet it:** blank when idle; one small card; strict frequency limits; it learns and gets quieter;
the "I'm lost" moment. The Beta build and the real-G2 run are the biggest risks of the whole weekend: do them
in the first hour (see [07](07-FIRST-HOURS-CHECKLIST.md)).

## Workday (core): track prize + DevRel meeting

"Build an AI agent that helps people succeed after they join a company." Mock data only, no real employee data.

| Criterion | Weight | How Glossary scores |
|---|---|---|
| Agentic logic & AI innovation | 30% | The jargon-pack agent plans, reads the sources, checks each term against them, proposes definitions with quotes, flags conflicts, and ends with a suggested next step. The recap suggests what to follow up on. Cards alone "just talk"; the agent is what earns this 30%. |
| New-hire & early-career relevance | 20% | Ramping into a new role is the whole product. |
| Responsible AI & trust | 20% | Human approves every term; sources and quotes on every card; "not sure" state; privacy by design; correction path. |
| Future of work | 15% | Onboarding, tribal knowledge, meetings. |
| UX & inclusivity | 10% | Text labels not colour-only cues, high contrast, keyboard-reachable controls. |
| Pitch & storytelling | 5% | |

**Workday's "Design for Trust" questions, and where each answer must live in the app:**

| Question | Answer in the product |
|---|---|
| What is the AI doing? | "What I did: read N sources, made N proposals, N not sure" + expandable step list |
| Why did it recommend this? | "Why jargon: …" line and the exact quote on each card |
| What data did it use? | Source document named on each card; the agent can only read the provided docs |
| What action does it take? | It only proposes. "Nothing reaches your glasses until you approve it." |
| Where do I approve, edit, reject? | Buttons on every card |
| What won't it do? | A visible "what this agent will not do" panel |
| When is a human needed? | Always for approval; "not sure" cards need a human definition; the agent's "Next:" step |
| What happens when it's uncertain? | A dashed "not sure" card with both quotes and no guessed definition |
| How do I correct it? | Learned → "Wrong?" → back to Review with a note; edits labelled "edited by you" |

Also prepare to show, per Workday's submission list: the problem, the user, how the agent works, what it does
autonomously, where the human is involved, what data and assumptions it uses, responsible AI, and how a real
company could use it.

## Sentry (add-on): guaranteed internship interview per member

**Hard requirement:** use **at least two Sentry products beyond error monitoring** (Session Replay, Logs,
Tracing, Profiling, Uptime, AI agent monitoring) and **show how observability shaped what you built**.

**Plan:** turn Sentry on in the first hours, not at the end, so real stories exist.
- **Tracing:** one trace per listening session with spans for each speech chunk, term match, card decision,
  card send, Gemini check and recap. A distributed trace from a click in the companion through the server to
  storage.
- **Logs:** structured logs for card shown / card held back (with the reason), gestures, model fallbacks,
  agent steps.
- **Session Replay** on the companion.
- **AI agent monitoring** on the Gemini calls (model, tokens, latency; prompts and answers not recorded).

**Story to collect during the build:** find the slowest spans and fix them, with before/after numbers. Write
the Devpost section as "what the trace showed → what we changed → the number after".

## MLH Best Use of Gemini API: swag

Gemini must do real work, not a token call. It does three jobs: the jargon-pack agent (function calling),
the "used it correctly?" check, and the "I'm lost" recap.

## MLH Best Use of ElevenLabs (conditional): earbuds

Enter only if **Scribe** wins a quick benchmark against Deepgram on jargon in noise and becomes the live
speech-to-text. Scribe is free during the event; it was never tested beforehand. Optional extra: reading the
recap aloud. Confirm the event credit amount at the start.

## Paper, Best Designed Hack (conditional): $1.5k / $1k / $500

Judged on design fundamentals, ease of use, personal craft, and not looking AI-generated. Code `LAHACKS26`
gives free Pro. Enter only if one teammate owns design all weekend. Designs must be made at the event. See the
Paper notes in [05-LESSONS.md](05-LESSONS.md).
