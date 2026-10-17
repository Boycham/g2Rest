# 06. The jargon pack and the data

## Fictional company only

Workday forbids real employee data, and rule 2 means the data is written at the event. Invent a company
(a name, a team the new hire joins, a few teammates with invented names) and write its documents at the event.
Pick a domain with vivid, demo-friendly jargon. A team with its own internal vocabulary works well (robotics,
game studio, logistics); avoid medical or financial themes (banned on Even Hub).

## Source documents (what the agent reads)

Write about four short internal docs, each a different kind, so sources can disagree:
1. An onboarding page for new hires.
2. A team wiki page.
3. A note from a recent standup or planning doc.
4. An **unfinished glossary stub** that someone abandoned, with some entries that defer elsewhere
   ("see X", "section missing", "TBD"). This is what makes the "not sure" path visible.

The agent may only read these provided docs. That is a feature in the trust story ("what data does it use").

## Term list: about 25–30 terms

Deliberately include:
- **Multi-word terms** ("two-word phrase" style), to test matching.
- **Acronyms** said as letters (like a priority level or "owner of a task"), and their spoken forms.
- **Terms with aliases** and likely speech-to-text misspellings.
- **One or two ambiguous terms** whose sources conflict or defer, so the agent must flag them "not sure".
- **Company jargon that is also an everyday word** (the false-positive risk). Decide per term whether to allow it;
  require a multi-word context alias if it would fire on normal speech.
- **General workplace jargon** a student might not know (RFC, dogfood, canary, freeze) alongside
  company-only terms (internal tool names, project codenames, room names).

Each term: term, aliases, a definition of at most ~12 words / ~110 characters, source doc, exact quote, a
confidence, and one line on "why this is jargon".

## The agent's job (Workday's "agentic" 30%)

Triggered by "Build my jargon pack" in the companion. The agent:
1. Plans, then lists and reads the sources.
2. For each candidate term, searches the other sources to check for conflicts or deferrals.
3. Proposes terms with definition, source, exact quote, confidence and "why jargon".
4. Flags uncertain terms instead of inventing a definition (a confidence floor of ~0.6 and a server guard).
5. Generates **aliases** for each term: spoken forms, acronym spellings, and likely speech-to-text mishearings
   (no everyday words). These feed the matcher; the human sees and can remove them on the review card.
6. Ends with a suggested **next step** for the human (for example, "Ask your onboarding buddy what X means").

Tools that worked: list sources, read source, search sources, propose term, flag uncertain. Server-side
checks: the quote must exist in the named source, definition length limits, argument validation, rejection of
terms another document defers. Proposals live outside the persistent store until approved.

Tests worth automating: at least 2 tool calls, at least 10 proposals, every quote found in its source,
definitions within the word limit, the ambiguous term flagged, a "Next:" step present. Run it several times.

## The demo standup script

Write a 60–90 second standup for 2–3 speakers at the event. Guidelines:
- Use **12–15 approved terms**, including one multi-word term, one alias, and the ambiguous term.
- Include **3–4 sentences with no jargon**, to show the app stays quiet.
- Include a moment where the **wearer uses a term correctly** (auto-learn) and a moment where someone
  asks "what does X mean?" (must not count as learned).
- Space terms so the one-card-per-30-s limit is visible but not frustrating.
- Keep a **ground-truth file**: each term and the line it appears in, to score recall and false cards.
- Read it at a normal pace like a real meeting; say terms exactly as written.

## Recordings (for the backup demo and any benchmark)

- Record the script with real voices: close to the mic (~30 cm) and at ~1 m (the "judge talking to the wearer"
  case), twice each. Convert to 16 kHz mono 16-bit WAV (on macOS: `afconvert -f WAVE -d LEI16@16000 -c 1 in.m4a out.wav`).
- Only people who agreed. Keep recordings out of git.
- For a crowd-noise test, use a real recording of a busy room (free-licensed, note the source) or mix 8+ of your
  own takes; not synthetic voices.
