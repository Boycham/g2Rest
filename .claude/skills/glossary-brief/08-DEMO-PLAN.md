# 08. Demo plan

## The story (about 3 minutes)

1. **Problem (20 s).** "Your first week, every meeting sounds like this." Play or act two lines thick with jargon.
2. **Set up (40 s, companion).** Tap "Build my jargon pack". Show the agent's steps, then one card: definition,
   source, exact quote, "why jargon". Approve one, edit one, show the dashed "not sure" card with the two
   conflicting quotes and write the definition yourself. Point at "Nothing reaches your glasses until you
   approve it" and the "what this agent will not do" panel.
3. **The moment (60 s, glasses).** A judge wears the G2. Teammates act out the short standup. A card appears
   once, in the line of sight; the next jargon term within 30 s is held back; jargon-free sentences show nothing.
   The wearer uses a term correctly and it's learned; the next time it's said, no card. Tap to dismiss.
4. **"I'm lost" (30 s).** The wearer swipes down mid-meeting. When the talking stops, a three-line recap appears.
5. **Close (30 s).** The Learned screen shows what they learned today and how. "It gets quieter the more you
   know." Mention privacy (no audio stored) and the Sentry story in one line each.

Have the three Even answers ready (see [01](01-PRODUCT-SPEC.md)) and the Workday trust table (see [02](02-SPONSORS.md)).

## Setup on the day

- Reset state before each judge (learned terms, cooldowns) with a reset control.
- Approve the demo pack in advance; keep 2–3 terms unapproved to show the review flow live.
- Speak close to the wearer. Expect a ~500-person hall: speech-to-text may return nothing when the crowd is as
  loud as the voice.
- Two phones if possible: one paired to the G2, one showing the companion.

## Backups, in order

1. **Live speech** from teammates standing close.
2. **Recorded human clip** of the standup, streamed through the real pipeline (speech-to-text, matcher, cards)
   from a hidden control in the companion, with the glasses mic muted while it plays. Same cards in the same
   order every run. Prepare a clean take and a lightly noisy take. Test it three times in a row before judging.
3. **Text injection** of the standup lines into the live session (skips speech-to-text, still real cards on the
   real glasses).
4. **Simulator** on the laptop if the G2 is unavailable (but Even requires a physical G2 run at judging, so treat
   this as a video-only fallback).
5. **Cached agent output** if Gemini is down when showing the review flow.

An untested idea that may help in noise: the companion streams the phone's mic (held near the speaker) into the
session instead of the glasses mic. If built, turn off loudness wearer detection and auto-learn in that mode.
Phone browsers only allow the mic over HTTPS.

## Demo video (required by Even)

Record before the deadline. Through-the-lens footage of the card is best; simulator footage is allowed. Show:
the review flow, a card appearing in a real conversation, a learned term going quiet, and the "I'm lost" recap.

## Devpost checklist

- Even Hub app name, Beta build uploaded, README with G2 install steps and every account/key a tester needs.
- Tracks selected: Even Realities, Workday, Sentry, Gemini (+ ElevenLabs / Paper only if they qualify).
- Workday section: problem, user, how the agent works, what it does autonomously, where the human is, data and
  assumptions, responsible AI, real-company impact.
- Sentry section: products used, and 2–3 "trace showed → we changed → number after" stories.
- "How we built it": the rule 2 disclosure (simulator practice and a written plan beforehand; all submitted code,
  data and designs made at LA Hacks), and the list of features built at the event.
- AI use: how Claude Code was used to build it, and how Gemini is used in the product (required by MLH rules).
- Public repo link with no keys in the history; README lists the frameworks and libraries used.
