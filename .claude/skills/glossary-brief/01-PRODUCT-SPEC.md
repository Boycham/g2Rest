# 01. Product spec

## Who, what moment, why G2

Even's judges ask these three questions. These are the answers.

- **Who is this for?** New hires and interns in their first weeks, sitting in meetings full of company jargon
  that nobody has explained.
- **What moment is it designed for?** Someone says a term you don't know, mid-sentence, and you can't stop the
  meeting to ask.
- **Why does it belong on G2?** The definition appears in your line of sight without picking up a phone; the
  mic sits on the wearer's head, so their own voice is easy to tell apart; and a one-card, quiet display
  stays out of the conversation.

Even's own principle: "One thoughtful interaction that feels natural on G2 is more valuable than a long list
of features." The card loop is the product. Everything else supports it.

## Differentiation (say this in the pitch)

G2 already ships a feature (Conversate) with live transcripts and auto "concept" cues, so a plain jargon
explainer scores poorly on originality. Glossary is different in three ways:

1. **Company-specific, human-approved vocabulary.** It only watches for terms from your company's own
   approved list, not general words, and every term has a source and a human sign-off.
2. **It learns what you know.** Every term starts as unknown and stops appearing once you've learned it.
   It gets quieter the longer you use it.
3. **"I'm lost" rewind.** One gesture marks that you lost the thread; you get a short plain-language recap
   when the conversation ends.

## The glasses experience

- The glasses only capture meeting audio. The server does speech-to-text and term matching and sends a card.
- **Card:** the term on one line plus a definition of at most about 110 characters (two lines on the 576×288
  display). One bordered card at the bottom of the display. Nothing on screen when idle.
- **Card rules:**
  - Only terms the user approved, and only terms they haven't learned.
  - At most one card on screen, and at most one new card per ~30 seconds (others are held back, not queued
    forever).
  - The same term is not shown again within ~2 minutes.
  - Only on confident recognition (drop matches below ~0.6 speech-to-text confidence).
  - A card disappears after a tap or after ~15 seconds.
- **The user starts out knowing no terms.** A term becomes learned:
  - automatically, when the wearer uses it correctly in their own speech (Gemini judges "used correctly?";
    asking "what does X mean?" is not correct use), or
  - by gesture: dismissing the same term twice.
- Learned terms persist across conversations and restarts.

## Gestures (final mapping)

| Gesture | Action | Why |
|---|---|---|
| Single tap | Done reading: dismiss the card. Second dismissal of the same term marks it learned. | |
| Swipe down | "I'm lost": mark the last ~60 s. | Long press does not exist in the SDK. |
| Swipe up | Show the last card again. A re-shown card does **not** count toward learned. | Wanting to see it again means not learned. |
| Double tap | **Always** the system exit dialog. Nothing else. | Even's review auto-rejects apps whose root-page double tap doesn't call the exit with the system dialog. |

Do not put gesture hints on the glasses display. Explain them in the companion and README.

## "I'm lost" recap

- Swipe down stores a marker at now − 30 s.
- When the conversation ends (about 20 s of quiet, or leaving the app), Gemini summarizes from the marker to
  the end in at most 3 short lines, in plain words, avoiding terms the user hasn't learned.
- Shown as a taller card sized to its text (a title plus 3 lines does not fit the normal card).
- Optional, only if ElevenLabs is in the stack: read the recap aloud privately through earbuds or the phone,
  as a voice on/off setting. G2 has no speaker.

## Companion phone app

A mobile-first web app. Screens, in priority order:

1. **Review (the important one).** "Build my jargon pack" runs the agent. Each proposed term is a card with the
   term, a short definition, the source document, the exact quote, a confidence, and a one-line "why this is
   jargon". Actions: **Approve**, **Edit** (marks "edited by you"), **Reject**. "Not sure" cards show the
   conflicting quotes and no invented definition; the human writes it. Header: "Nothing reaches your glasses
   until you approve it." A visible "what this agent will not do" panel. A collapsible "show every step"
   list of what the agent did. No "approve all" button (bulk approval invites approving without reading).
2. **Learned.** Terms the user has learned, how they learned them, and a **"Wrong?"** action that sends a term
   back to Review with a note.
3. **History / meetings** with the recaps, and **Live** (mirror of what the glasses show) only if time allows.
4. A chat to configure things (company, card frequency, cards on/off) is a stretch goal.

## Privacy, stated simply

Audio is streamed to speech-to-text and discarded, never stored. Transcripts live in server memory for the
length of a session and are wiped at the end. The only things saved are the approved term list, which
terms are learned, and the recaps. Observability tools never receive prompts, answers, transcripts or audio.
Demo only with people who agreed to be recorded; all company data is fictional.

## Out of scope this weekend

Real company integrations, multi-user accounts, pairing codes, iMessage or other chat bots, scheduled
digests, any medical, financial or emergency feature (banned on Even Hub).
