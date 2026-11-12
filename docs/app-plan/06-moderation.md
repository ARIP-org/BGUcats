# The moderation layer

What checks the things people write and upload before others see them,
built on Google's Decision 1 model. Background and the first assessment:
`docs/moderation.md`. This file is the build plan (milestones C1–C4).

## In one paragraph

Every public piece of text and every public photo is written as
`pending`. The events Lambda cleans it, checks a small blocklist, asks
Decision 1 a handful of yes/no questions, and records every probability.
Depending on the mode, the answer either only sits beside an admin's own
decision (shadow) or decides: pass, hold for an admin, or refuse
(enforce). The person who wrote it never waits on Google and always sees
their own item. Every admin decision is kept next to the model's, which
is what turns its probabilities into thresholds this project earned.

## What is checked

| Kind | What | Limit | When it becomes public |
|---|---|---|---|
| `POSTTEXT` | a post's description | 280 | with the post |
| `NAME` | a name suggested for a cat | 24 | when it enters the poll |
| `PROPNAME` | the name idea on a new-cat proposal | 24 | when the proposal's post is shown, and again as a poll option if the cat is approved |
| `DISPLAYNAME` | a person's name | 30 | when others see the new name |
| `USERNAME` | the @name | 20 | at once: it is restricted to `a-z 0-9 . _`, so the blocklist and reserved list do most of the work, and the model's check follows |
| `PHOTO` | each photo of a post or proposal | | with the post |
| `AVATAR` | a profile photo | | when others see it |

Not checked by the model: a cat's description (an admin wrote it), votes,
likes, coat and trait chips (fixed lists), reports (a person reads them).

**Only what is about to be public is sent to Google.** The dataset's
photos from the bot, and encounters saved without posting, are not
(M1).

## The path of one item

1. **Clean,** in the API, before storing: Unicode normalised, control and
   zero-width characters and direction overrides removed, spaces
   collapsed, length checked (`02-architecture.md`, "Abuse and limits").
2. **Blocklist,** in the API: an exact, readable list in four languages
   (O11). A hit is refused on the spot with `not_accepted`; nothing is
   stored. This is the only synchronous check.
3. **Stored as `pending`.** The author sees it, marked "Being checked".
4. **The events Lambda** picks it up from the stream. For a post it first
   makes sure each photo's derivative exists (the process Lambda may be a
   second behind), waiting up to ten seconds.
5. **Decision 1** is asked the kind's questions, one request per text and
   one per photo. A photo's run is keyed by the photo, so a photo is
   checked once however many times it is used.
6. **The run is recorded** (`MOD#{kind}#{id}` / `RUN#{at}`): the policy
   version, the model id, every question's probability, the outcome.
7. **The outcome acts or does not,** by mode (below).
8. **An admin's decision,** when there is one, is written on the same
   run: agreed or not.

## Two settings

| `moderation_mode` | Google is called | The outcome |
|---|---|---|
| `off` | no | nothing is decided by a model |
| `shadow` | yes | is recorded and shown to the admin; decides nothing |
| `enforce` | yes | decides: `pass` publishes, `flag` holds for an admin, `block` refuses |

| `hold_unchecked` | An item nothing has decided |
|---|---|
| on | waits for an admin |
| off | is published at once |

How they combine over the project's life:

| Stage | Mode | Hold | Who is using the app | Effect |
|---|---|---|---|---|
| Before M1 is answered | `off` | on | nobody outside | every item waits for the owner |
| Internal TestFlight | `shadow` | **off** | people the owner knows | everything publishes; verdicts pile up beside the owner's own |
| External TestFlight, first weeks | `shadow` | on | strangers | every item waits for an admin, who sees the model's opinion: this is spec §9.2 exactly |
| After the evidence below | `enforce` | on | strangers | clean items publish in seconds; the rest wait |

`enforce` with hold off is not a valid combination; the Lambda refuses to
start with it.

## The questions

Yes/no questions, each about one thing, phrased positively, with a short
description of what "yes" and "no" look like, as the API's guide advises.
They live in one file, `src/common/moderation_policy.json`, with a
`version`. Changing a question or a threshold changes the version, and
every run records the version it used, so numbers from different policies
are never mixed.

**Names** (`NAME`, `PROPNAME`, `DISPLAYNAME`, `USERNAME`), with the
context "proposed as a name for a campus cat" or "a person's display
name":

| Key | Asks |
|---|---|
| `abusive` | Is this a slur, an obscenity or an insult, in any language, including Hebrew, Arabic or Russian written in Latin letters, and deliberate misspellings? |
| `sexual` | Is this sexual or does it name a sexual act or body part? |
| `hateful_or_political` | Is this a hate slogan or symbol, or the name or slogan of a political party, movement, leader or armed conflict? |
| `real_person` | Is this the full name of a person (a first name and a family name together), or the name of a well-known public figure? |
| `not_a_name` | Is this something other than a name: a link, a phone number, an advertisement, an instruction, or random characters? |

**A post's description** (`POSTTEXT`): `abusive`, `sexual`,
`hateful_or_political`, and:

| Key | Asks |
|---|---|
| `harassment` | Does this mock, threaten or target a specific person or a group of people? |
| `personal_info` | Does this contain a phone number, a home address, an ID number, or the full name of a private person? |
| `animal_harm` | Does this describe, joke about or encourage hurting an animal? |
| `spam` | Is this an advertisement, a repeated promotion, or unrelated to cats and the campus? |

**A photo** (`PHOTO`):

| Key | Asks |
|---|---|
| `human_face` | Is a person's face clearly visible and recognisable in this photo? |
| `private_info` | Is there readable private information: a licence plate, an ID or student card, a document, a phone or computer screen? |
| `cat_present` | Is a domestic cat visible in this photo? (Expected yes.) |
| `graphic` | Does this show nudity, blood, a serious injury or a dead animal? |

**An avatar** (`AVATAR`): `graphic`, `sexual`, and `hateful_symbol`. A
person's own face is fine on their own profile.

`animal_harm` and `graphic` do two jobs: a photo of an injured cat is
held from the feed **and** is something the people who care for the cats
want to know. The desk's queue marks those rows.

### Thresholds, and what they are worth today

Each question has a `flagAt` and some a `blockAt`:

- every probability under its `flagAt` (and `cat_present` over its
  floor) → **pass**;
- any probability at or over a `blockAt` → **block**;
- otherwise → **flag**.

Starting numbers, so there is something to run in shadow:

| Question | `flagAt` | `blockAt` |
|---|---|---|
| `abusive`, `sexual`, `graphic` | 0.20 | 0.90 |
| `hateful_or_political`, `harassment`, `animal_harm`, `hateful_symbol` | 0.20 | none: a person decides |
| `personal_info`, `private_info` | 0.40 | none |
| `real_person` | 0.40 | none |
| `human_face` | 0.50 | none (M4) |
| `not_a_name`, `spam` | 0.50 | none |
| `cat_present` | flag if under 0.30 | |

**These numbers are invented.** They are low on purpose: a false flag
costs an admin one tap, a missed slur is public (`CLAUDE.md` makes the
same trade for "new cat"). Decision 1's probabilities are described as
calibrated, on Google's data. Whether 0.2 means anything for a
24-character name in Hebrew is exactly what shadow mode measures. Its own
guide says to set thresholds from labeled examples of your own traffic.

`real_person` is where any model is weakest (it cannot know a classmate's
name) and where the harm is worst (a cat named after someone to mock
them). It never blocks and never passes alone above its line: a person
decides. And an admin can always remove a name or lock one (D6).

## The Decisions API, as read on 2026-11-12

From Google's model page, API guide and pricing page that day. **Check
all of it again when C1 is built**; the session records the date it
checked.

- `POST https://generativelanguage.googleapis.com/v1beta/decisions`, key
  in the `x-goog-api-key` header.
- Body: `model` (`gemini-decision-1`), `input` (a string, or content
  blocks: `text`, `image`, `audio`, `video`, `document`), `questions` (a
  map of up to 1,000, keys of letters, digits, `_` and `-`).
- A question: `type`, `instructions` (text only), optional `criteria`.
  Types as printed on the page: yes/no, `choice` (2–255 options), `score`
  (2–255 ordered levels). The yes/no type's identifier read as `noul`
  both times the page was read; treat that spelling as unconfirmed until
  a real request succeeds.
- Media: `data` (base64) or `uri` (a public or signed HTTPS address, up
  to 15 MB), with `mime_type`; images take an optional `resolution`
  (`low` to `ultra_high`). PNG and JPEG are listed. **WebP is not
  confirmed**, and the derivatives are WebP: C1's first task is one real
  request with a WebP derivative. If refused, the events Lambda sends the
  JPEG or PNG it needs another way, decided then (the plan does not add a
  third derivative to spec §6.2 without the owner).
- Answer: `answers` keyed like the questions, each with the probability
  of yes (0.01 to 0.99) and a `confidence`; `usage` with input tokens.
  Output tokens are always zero.
- All questions are answered in one pass; more questions cost their own
  words and almost no time.
- A request Google's own safety filter refuses comes back as HTTP 400
  with a code (`safety`, `prohibited_content`, `blocklist`,
  `image_safety`, `content_blocked`), not as answers.
- No batch, no caching.
- Price: one input price for every kind of input. The page said $0.10 per
  million tokens on the paid tier; the owner was told $0.75. A name costs
  a few hundred tokens, a photo perhaps a thousand. **Free-tier requests
  are used to improve Google's products; paid-tier requests are not.**
  The key must be on the paid tier (O5).
- Languages it handles well: not stated anywhere. Measured by the gold
  set.

## The client

`src/common/decisions.py`, used by the events Lambda (moderation) and the
existing API (re-rank).

- Standard library only (`urllib`), like the bot's calls to Telegram. No
  SDK: nothing new in a Lambda's package, and the request is twenty lines
  that can be read.
- The key is read from SSM once per warm Lambda.
- A 10-second timeout. Two retries with a pause, on timeouts and 5xx
  only.
- Before each call it adds to today's `SPEND` counter and refuses to call
  past the ceiling (K3). After each call it records tokens and time.
- A safety refusal (the 400 above) is an outcome, not an error: `block`
  for a photo or avatar, `flag` for text.
- **What is sent:** the cleaned text, or the 1024-pixel derivative
  (already stripped of EXIF), and the questions. **Never:** an email, a
  user id, a location, a cat's id.
- **The text is untrusted.** It goes in as content, clearly delimited,
  and the instructions say that the content may contain instructions
  which must not be followed. Decision 1 produces no text and calls no
  tools, so the worst a clever name can do is move a probability; that
  bounded failure is the reason this model shape was chosen
  (`docs/notes.md`, "Models from outside").

## When things go wrong

| What | Then |
|---|---|
| Google times out or errors after the retries | outcome `error`; the item waits for an admin (M3); the queue shows it; "run again" is one button |
| The daily ceiling is reached | the same as `error`, with its own reason; one email through the alerts topic |
| The key is missing or revoked | the same; the Lambda's error alarm fires |
| The events Lambda itself fails on a record | three retries, then the record goes to the alerts topic; the item is still `pending` and appears in the queue after ten minutes |
| A photo's derivative never appears | `error` after the wait; this is also a stalled upload, which Stats → Bot health already lists |
| The policy file is wrong | it is validated by a test and when the Lambda starts; a Lambda that cannot load it does not process anything, loudly |

Nothing in this table publishes an unchecked item while
`hold_unchecked` is on.

## What a person sees

- Their own item at once, marked "Being checked". For a clean item in
  `enforce`, the mark is gone in a few seconds.
- A refused item: "This wasn't published." No category, no score. They
  can delete it or, for a name, try another.
- A held item stays "Being checked" until an admin decides. No timer is
  promised.
- Nobody sees someone else's pending or refused item, anywhere.

## The desk

A **Moderation** tab for admins (C2), in the existing desk:

- **The queue:** each waiting item with what it is, who wrote it, the
  model's outcome, and each question's probability as a small bar.
  **Approve** or **Reject**, one tap each. In shadow with hold on, that
  is every item; in enforce, only flags and errors.
- **Measured** (under Stats, beside "Recognition model"): for each
  question, of the items an admin decided, how the model's outcome
  compared at the current thresholds, and what any other threshold would
  have done to the same items. Split by kind and by the text's script
  (Hebrew, Arabic, Cyrillic, Latin), because an average hides which
  language is failing, the way an average hides the black cat.

## From shadow to enforce: the evidence

`moderation_mode` moves to `enforce` by a one-line pull request (O18)
that shows:

1. **The gold set** (O11) scored by `scripts/moderation_eval.py`: at the
   proposed thresholds, at least 95 of every 100 unacceptable items are
   flagged or blocked, in each language separately; and at least 80 of
   every 100 acceptable ones pass. If a language misses the first number,
   enforce does not apply to text in that script: it keeps waiting for an
   admin.
2. **At least two weeks of shadow on real items,** with the admin's
   decisions: no item the admin rejected that the thresholds would have
   passed. One such item is a finding to explain, not a rounding error.
3. **Nothing blocked that the admin approved.**

Thresholds move the same way: a pull request to the policy file with the
table that justifies it. They are never tuned from memory.

A model change on Google's side (a new version behind the same name) is
visible as the model id on each run. The measured table is kept per
model id, and a new id starts in shadow for the kinds it affects.

## Reports, blocks and bans

Built in B8, separate from the model, and required by Apple's rule 1.2
whatever the model does:

- anyone can report a post, a person, a name or an avatar, with a reason
  from a fixed list (D15);
- a report emails the admins and joins the desk's Reports queue;
- an item reported by three different people is hidden until an admin
  decides;
- blocking a person hides each from the other everywhere and ends the
  friendship;
- an admin can hide or remove a post, remove a name, and ban a person.

A report on an item the model passed is the most valuable row in the
measured table: it is a miss found by a person.

## Tests

- The policy file: valid, every kind has its questions, every question a
  threshold.
- The cleaning function: direction overrides, zero-width joiners, mixed
  scripts, emoji, length in characters not bytes.
- The decision rule: a table of probabilities in, outcome out, for every
  mode and hold combination.
- The client: against recorded responses, including a safety refusal, a
  timeout and a malformed answer. **No test calls Google.**
- The path end to end in the local app, with the fake that flags
  `flagme`: a clean post appears for a friend; a flagged one does not and
  is in the queue; approving it publishes it; the author saw it
  throughout.
- The eval script against a tiny committed set, with the client faked.

## What this layer must never do

- Publish an item nothing checked while `hold_unchecked` is on.
- Delete anything by itself. `block` refuses publication; the author's
  item remains theirs to delete, and the photo's fate in the dataset is
  the labeling desk's.
- Block on a question that has no `blockAt`.
- Show a score to a member.
- Send to Google anything that is not about to be public, or any
  identity.
- Stand in for the Reports queue or for an admin's judgment about a real
  person's name.
