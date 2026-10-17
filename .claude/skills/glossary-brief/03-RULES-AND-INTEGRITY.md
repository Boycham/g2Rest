# 03. Event rules and integrity

The event is **Oct 17-18, 2026**. The rules text the team has carries an old date (an April deadline); ignore
that date and **confirm the actual submission deadline at check-in**.

## Rules that matter

| Rule | What it means for us |
|---|---|
| Max 4 members | Confirm the roster. |
| 1. Students only, no privileged roles | Nobody on the team may be an organizer, judge, mentor or sponsor rep. Borrowing a loaner G2 is fine. |
| 2. All work at the hackathon | See below. This is the one real risk. |
| 3. Stop at time up | Code freeze at the deadline. Record the demo video and deploy **before** it. After it, only Devpost text edits. |
| 4. Submission deadline | Confirm the exact time on site. |
| 5. Disqualification / MLH Code of Conduct | Glossary records speech: only capture teammates and volunteers who agreed. Fictional company, no real employee data. |
| 6. Accepted, RSVP'd, in person | Every member must be accepted, RSVP'd and physically there. |

## What rule 2 means

Rule 2 says all work must be done at the hackathon. **2.1:** pre-existing work is allowed only if it is open
source. **2.2:** judges score only the features built during the event.

The team practiced privately on the simulator before the event, on the same product idea. That practice was
not open source, and even if it were, extending it would leave little for judges to score. So:

**Allowed before the event (already done):** the idea, this spec, reading SDK docs, learning lessons, setting up
accounts and API keys, installing tools.

**At the event:**
1. Create a **new empty repository after hacking starts**, so the first commit is timestamped inside the event.
   Commit often; the history is the evidence.
2. Write **all code** there. Do not copy files or paste chunks from any earlier project. Re-deriving from the
   lessons in this folder is fine.
3. Write the **fictional company and its documents** at the event (see [06](06-JARGON-PACK-AND-DATA.md)).
4. Make the **Paper designs** at the event.
5. Public SDKs, Even's templates, npm packages, and Even's own Claude Code plugin skills are open source or
   sponsor tools and are fine to use.
6. **Disclose on Devpost** under "How we built it": we prototyped on the Even simulator beforehand to learn the
   SDK, and all submitted code, data and designs were made at LA Hacks. Transparency is what protects us.
7. If in doubt, ask an organizer at check-in ("We practiced with the Even SDK before the event; is starting a
   fresh repo here OK?") and get the answer in writing (a Discord message).

**Gray area: pre-written plans and prompts.** Planning before the event is allowed; code is not. This brief and
the short kickoff prompt in [BUILD-PROMPT.md](BUILD-PROMPT.md) contain no code, data or designs, only decisions
and lessons, and all code is generated and written at the event. Keep it that way: never add code, schemas,
prompts for the in-app agent, or the company data to this folder before the event. Say on Devpost that a
written plan and Claude Code were used.

## MLH's recommended rules (check which ones LA Hacks adopts)

MLH's organizer guide recommends these rules, and many MLH events use them. Treat them as required unless
organizers say otherwise:
- "You may not work on your project before the event." No reusing code from previous projects.
- **Credit AI use.** "You may use LLM/ChatGPT/AI, but must state how you did so in your Devpost submission."
  Not crediting it means disqualification. Keep a running log of how Claude Code (and Gemini in the product)
  were used, and paste it into Devpost.
- "Your project should not be a reskin of an existing AI tool." Glossary's differentiation from G2's built-in
  live transcript and concept cues is in [01](01-PRODUCT-SPEC.md); say it in the pitch.
- **Submit the code as a public link** on Devpost, with API keys removed. Make the repo public before the
  deadline (an MIT license is a good idea) and check the full history for keys first.
- **List the public frameworks and libraries used in the README.**

Source: MLH organizer guide, "Rules for your hackathon" (guide.mlh.com). Also follow the MLH Code of Conduct.
