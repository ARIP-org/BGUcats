# Moderation

**Nothing here is built, and the decision to build it has not been taken.**
This is the design note for the moderation layer the phase 4 app will need,
written 2026-11-12 after reading the prototype's screens and Google's
Decision 1 model page. It records what the surface actually is, what a model
can and cannot do about it, and the one place a model must not go.

Phase 4 is DEFERRED in `CLAUDE.md` and the spec's §10 still says no public
read path. Read those first; this does not amend them.

The prototype the surface is read from:
`https://claude.ai/artifact/BmuxNRNA2SGsuoUXT2f9k6` (19 boards, 2026-11-11).

## The surface is small, and that is a design choice already made

Every field in the prototype a person can type into or upload:

| Surface | Where | Bound |
|---|---|---|
| Cat name suggestion | Cat profile, name poll | 24 characters |
| Display name | Profile page | 30 characters |
| Phone number | Profile page | `type="tel"`, 13 characters |
| Avatar | Profile page | `type="file"` |
| Cat photos | Scanner → Post | image |
| Report / Block | Friends, the ••• menu | human-initiated, no text |

Search is a seventh input and is not a surface: nothing is stored or shown
to anyone else.

**What is not there: a caption field.** No `<textarea>` anywhere in the
232 KB Feed component, and no comments. A post is a photo plus a cat
identity. The name poll is a 24-character suggestion and votes.

That is the cheapest moderation decision available, and the prototype
already makes it. A caption is where the cost lives: unbounded text carries
harassment that no 24-character name can, and it turns a bounded problem
into a staffed one. Adding one is a product decision with a moderation bill
attached, not a UI tweak.

Two other things in the prototype are bigger changes than they look, and
belong to whoever decides phase 4 rather than to this note: a phone number
is PII the project does not collect today, and "Add a new cat" in the
scanner puts cat creation in a contributor's hands, against
"cats are admin-curated" in `CLAUDE.md`.

## What the surface needs, question by question

Not one "is this OK" score. The right threshold for a slur is not the right
threshold for a face in frame, so each of these is its own question with its
own threshold.

**Names** (cat names, display names):

- a slur or obscenity, in Hebrew, English, Russian or Arabic
- the name of a real identifiable person — the harassment vector is naming a
  cat after a classmate, and it is the hardest of these for any model
- a political slogan or party
- sexual content
- not a name at all: spam, a URL, a phone number

**Photos** (cat photos, avatars):

- an identifiable human face
- a readable plate, badge, ID card or document
- a domestic cat as the main subject

The last one is not moderation. It is the "is this a campus cat" validation
`CLAUDE.md` says does not exist, and the scanner's "Add a new cat" is where
it would be needed.

Note which risks these are. An off-the-shelf moderation taxonomy is built
for abuse *directed at someone* in a sentence, and its image classes are
about nudity and violence. The real exposure here is incidental people in a
cat photo — a class no such taxonomy has — in a project that already rounds
GPS to ~100 m so it cannot reveal where a contributor was standing.

## Gemini Decision 1

From the model page, read 2026-11-12. It is not a moderation endpoint; it is
a typed-question evaluator.

- **Yes/no** → a calibrated probability from 0.01 to 0.99, plus a confidence.
- **Single-select**, 2–255 options → the top option, per-option
  probabilities, a confidence.
- **Rubric rating**, 2–255 ordered levels → a probability-weighted expected
  score, per-level probabilities, a confidence.
- Input: text, image, video, audio, PDF. 262,144 tokens. Up to **1,000
  independent questions over one shared input**.
- **Zero output tokens.**
- Not supported: function calling, structured outputs, text generation,
  thinking, caching, batch, Live API, search grounding.

Why that shape fits this project rather than merely working:

- **The job is a verdict, not prose.** A general chat model returns text to
  parse and a confidence it made up. This returns a number to threshold and
  a confidence on the number. The whole discipline in `CLAUDE.md` — earn
  thresholds from the live record, calibrate on held-out identities, report
  knowns and unknowns apart, bias toward the cheap error — needs a
  calibrated number to operate on.
- **Many questions over one input** is exactly the list above: six yes/nos
  on a name, or three on a photo, in one request, each independently tunable.
- **It needs no new AWS resource type.** This matters more than it sounds.
  Bedrock Guardrails or Rekognition would mean widening
  `infra/main/allowed-resource-types.txt`, the bootstrap deploy role *and*
  `infra/org/scp.tf` — three owner decisions. An outbound HTTPS call needs
  none of them: Lambda is outside a VPC with full internet access, and the
  key has a path through `infra/scripts/set-secret.sh` into SSM
  SecureString. It is the cheapest thing that could be added to this
  architecture.
- **A model with no text output is a small injection target.** A cat name is
  attacker-controlled text entering a model. With no output tokens and no
  tool calling, the worst case is a flipped probability — not an action and
  not an exfiltration.

## Where it must not go

**Not the match list.** Single-select over 2–255 options looks exactly like
"which of our 50 cats is this". It is the classifier `CLAUDE.md` bans
permanently, with an API in front of it. Taking options per request dodges
one of the three stated objections — no retraining per cat — but not the
others: no embedding space, no enrollment templates, no honest
"I don't know this one" against an open set, a cost and a network round trip
per query where the browser does it free today, and it would hollow out the
1b/1c track that is the project's actual technical story.

**One recognition use is worth measuring, in 1b.** Pairwise verification as
a reranker: the embedding search returns the top-k, then one yes/no per
candidate — "are these two photos the same individual cat?" — over a shared
input. That is the "local-feature rerank of the ANN top-50" slot already in
the recognition architecture, and a calibrated yes/no suits that slot better
than ALIKED + LightGlue, which will not run in a browser. It needs no labels
and no BGU training data, which is the lever `research/FINDINGS.md` round 3
is short of at 3–5 of 13 right first. Research track, measured, not
production.

## Four conditions, if it is built

1. **Shadow mode first.** Record the verdict with its model version — a
   `MODERATION#{version}` item beside `PREDICTION#{version}` and
   `VECTOR#{version}` — and score it against what the admin actually
   decided, before any threshold acts on anything. Same shape as 1c.
2. **Never on the blocking path.** Store `pending`, moderate
   asynchronously, flip the status. Never in the ingest handler. Photo
   checks belong in the process Lambda on the S3 event, beside pHash and
   the derivatives. A vendor API that is slow or down must never cost a
   submission.
3. **Flag, never drop, and the admin keeps the accept.** Same rule as
   near-duplicates. Bias toward false flags: a false flag costs an admin one
   tap, a slur on a public cat name is permanent. "Is this a real person's
   name" stays human-decided, because that is where a model is weakest and
   the damage is worst.
4. **Decide the privacy disclosure deliberately.** This sends contributors'
   photos, and their display names, to Google. Defensible — part of it is
   *for* their protection — but it is a change to the project's privacy
   posture, and it belongs in the spec and in whatever the app tells people,
   not in a pull request.

## Cost

Input is $0.75 per million tokens (owner, 2026-11-12; the model page points
at the pricing page rather than naming it). Output is free, there being none.

- A 24-character name with six questions: a few hundred input tokens, about
  $0.0002. Ten thousand names, about $2.
- Images run a few hundred to ~1,000 tokens each. Moderating the entire
  2,000-image backlog: under $2.

No caching and no batch means no bulk discount and the instructions are
re-sent every call. At this volume that is noise. For comparison, AWS for
production is about 2 cents a month (`docs/notes.md`, Money) — this would be
the project's largest variable cost and still be inside the $10 budget
email.

Cost is not the reason to hesitate. The reason to hesitate is that a
calibrated probability is calibrated on someone else's distribution, and
nobody has measured this one on BGU names in four languages.

## The honest-percentage problem

The prototype's scanner shows "92% / 74% / 61% match" over "Closest matches
from 48 campus cats".

The model manifest ships `"thresholds": null` on purpose, because on BGU
photos the top scores of right guesses, wrong guesses and never-seen cats
overlap, and the first guess is right on 3–5 of 13 labeled sessions
(`research/FINDINGS.md`, round 3). A cosine similarity is not a probability.
Rendering one as a percentage promises a calibration the system does not
have, next to a number that is wrong two times in three.

Two honest options: show rank only ("closest match", no number), or get a
calibrated score — which is the one thing Decision 1 natively produces. If
the percentage is wanted, it has to be earned; it cannot be borrowed from
cosine.
