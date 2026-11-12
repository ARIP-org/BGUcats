# The re-ranking layer

Using Decision 1 to reorder the recognition model's shortlist. Milestones
R0–R3. It starts as a research experiment because nobody knows yet
whether it helps.

## What it is, and the line it must not cross

The recognition model in the phone ranks every cat by embedding
similarity and offers the top three. That stays. Re-ranking takes the
top few of that list and asks Decision 1, for each candidate: **"is the
cat in these new photos the same individual as the cat in these
enrolled photos?"** A yes/no question per candidate, a probability per
answer, and the candidates are reordered by it.

This is the slot the recognition architecture already has: "local-feature
rerank of those 50 only". `research/FINDINGS.md`, round 2, found the
planned keypoint matcher barely helps on plain-coated animals and cannot
run in a browser. A model that can look at two photos and compare faces
and markings is a different tool for the same slot.

**It is not a classifier over our cats, and must never become one**
(`CLAUDE.md`, "No softmax classifier over our cats, ever"). The
difference is concrete:

| | Allowed | Not allowed |
|---|---|---|
| Question | "same individual as this candidate?", once per candidate, each answered alone | "which of these 50 is it?" |
| Candidates come from | the embedding's ranking over enrolled templates | a list of all cats |
| A new cat | is still just a cat with templates; nothing is retrained or re-listed | needs to be added to a list of options |
| "None of these" | every answer can be low | the answers are forced to share 100% |
| Without it | the app works exactly as today | the app cannot recognise |

Decision 1's single-select type over cat names is the banned classifier
with an API in front of it (`docs/notes.md`). It appears in R0 only as a
comparison, to be able to say what it does, and nowhere after.

**It ranks. It never decides.** No auto-accept, no "new cat" verdict.
The manifest's `"thresholds": null` stays until the live record earns
thresholds, as `docs/app-backlog.md` already says.

## R0. The experiment (research track, no AWS)

Lives in `research/`, imports nothing from `src/`, adds nothing to any
Lambda. One new module, `research/catreid/pairwise.py`, with its own few
lines of HTTP (it cannot share `src/common/`), the key from the
environment, and every response cached on disk under `research/runs/`
so a run can be repeated without paying twice.

**Data.** The labeled BGU sessions, exported to a local folder by the
owner (O20). They are the only numbers that may be quoted. A public
set with real session boundaries may be used first to check the
machinery, and is never reported as the system's accuracy.

**Protocol.** The same as round 3, so the numbers sit beside it:
leave one session out; rank it against every other labeled photo with
the frozen embedding; take the top K; re-rank those; score against the
label. Split by session, never by photo. Cats with one session are the
"never seen" half.

**What is varied,** one thing at a time:

| | Values |
|---|---|
| K, the shortlist | 3, 5, 10 |
| Enrolled photos shown per candidate | 1, 2, 3; chosen from different sessions when the cat has them (round 1: variety across encounters is the lever) |
| Query photos shown | 1, 2, 3 |
| One request for all candidates, or one per candidate | both |
| Image resolution setting | low, medium |
| The question's wording | two versions, fixed before looking at results |
| How the two scores combine | re-rank's order alone; a weighted mix with the cosine |

**Controls,** because a model that looks at whole photos can be right for
the wrong reason:

- Candidate keys and order are shuffled per request. The guide says ties
  go to the alphabetically first key.
- Pairs of *different* cats photographed in the *same* place, and of the
  *same* cat in *different* places, are reported separately. If "same
  place" predicts yes better than "same cat", it is matching the bench,
  not the cat (round 2 asked the same of the embedding).
- The per-cat table, always. The plain-coated cats will carry the
  failures, and an average would hide it.

**What is reported,** as round 4 of `research/FINDINGS.md`:

- right cat first, and in the top three, for the embedding alone and for
  each variant, on the same queries;
- per cat;
- for known and never-seen cats separately: the highest "same" answer.
  Whether those two distributions separate is the open-set question, and
  the first evidence of a threshold worth earning;
- how often the model says 0.8 and is right 8 times in 10 (its
  calibration on these cats, not Google's);
- tokens, cost and time per query.

**The honest limit.** On 2026-10-29 there were 13 sessions that could be
queried as a known cat. A difference of two sessions is noise. R0 can
show the machinery works and whether the effect is large or absent; it
cannot justify going live. That needs the shadow record (R1–R2). Say so
in the findings.

## R1. Shadow, in the product

With `rerank_mode = shadow`, every app encounter is re-ranked and the
result recorded; nobody sees it.

**The route:** `POST /api/encounters/{id}/rerank`, in the existing API
beside the other capture routes, for the encounter's owner.

- The phone sends the model version and its own top K with their
  scores. It sends this through the outbox after the photos are
  confirmed, so the server has their derivatives.
- The server refuses if the session already has a label: a guess made
  after the label is not a measurement, the same rule and the same
  condition as `POST /api/sessions/{id}/prediction` (absent **or null**
  `catId`; `docs/notes.md`).
- It picks the query photos (up to two of the encounter's, spaced, never
  the first two of a burst) and, for each candidate, up to two enrolled
  photos from different sessions, through the photos-of-a-cat index.
- One request to Decision 1 through `src/common/decisions.py`: the
  photos as signed addresses or inline, a text line before each group
  ("QUERY", "CANDIDATE k7"), one yes/no question per candidate, keys
  random per request.
- It writes `SESSION#{id}` / `RERANK#{version}` in `bgucats-data`:
  the candidates as received, each one's "same" probability, the new
  order, tokens, time. First write per version wins.

**The version** is a hash of everything that changes the answer: the
Decision model's id, the question's wording, K, how many photos per side,
the resolution, and the embedding model's version. Two records with
different versions are never compared as if they were one experiment.

**The ceiling** (K3) and the per-person limit apply. Over either, the
route answers that it did nothing, and the app goes on.

## R2. Measured

Stats → Recognition model already compares the model's guess with the
label, using `summarize` in `web/recognition.js`. It gains the same table
for the re-ranked order, on the same sessions, side by side: right first,
in the top three, per cat; and for proposals that an admin approved as
new cats, the highest "same" answer the re-rank gave.

One scoring function for the replay, the live record and the re-rank, as
now. No second implementation.

## R3. Live

Only after the bar below, and K1.

What changes from shadow:

- The phone cannot wait for an upload on campus Wi-Fi, so it sends a
  small copy of the query photo with the request (at most 512 pixels, at
  most 100 KB), and the route uses that instead of the derivative.
- **"Which cat?" never reorders under a finger.** The three candidates
  appear when the re-rank answers or after 2.5 seconds, whichever is
  first. Whatever is shown stays. If the answer comes late it is recorded
  and not used.
- No signal, the ceiling reached, an error, a slow answer: the
  embedding's order, exactly as today. Capture never depends on Google.
- The pick records which order the person was shown and where it came
  from, so the product-loop numbers stay honest about what was measured.

**The bar** (K2, proposed): on at least 100 labeled encounters of cats
that were already enrolled, re-ranked while in shadow,

1. the right cat is first at least 10 points more often than with the
   embedding alone;
2. it is in the top three no less often;
3. no single cat with at least five encounters gets worse by more than
   one encounter;
4. the median answer arrives in under 2 seconds.

The pull request that sets `rerank_mode = live` shows the table.

## What it costs

One request per encounter: two query photos and, for K = 5 with two
enrolled photos each, ten more. At the low or medium resolution setting
that is a few thousand tokens. At either price on record ($0.10 or $0.75
per million) a re-rank costs a fraction of a cent, and a thousand a day
stays under the $2 ceiling. R0 measures the real figure.

## What can go wrong, said now

- **Plain-coated cats.** A black cat is hard for a person looking at two
  photos. Expect the per-cat table to show it.
- **It matches the place.** A cat is usually photographed where it lives,
  and so are its enrolled photos. The controls in R0 exist for this.
- **The enrolled photos are the bottleneck.** A cat with one session
  offers one view. Round 1's lesson applies: re-encounters and merges are
  what improve this, more than any model.
- **The model changes under the same name.** The version hash includes
  the model id for that reason; a new id starts in shadow.
- **A second vendor in the recognition path.** Which is why it is only
  ever an optional reordering of something that works without it.
- **Two different pipelines' numbers get mixed.** Browser vectors and
  Python vectors already differ slightly and are never mixed
  (`CLAUDE.md`). The same holds here: a re-rank record names the
  embedding version it reordered.

## What it must never do

- Run as the only recogniser, or over a list of all cats.
- Decide: accept a match, declare a new cat, label a session.
- Reorder candidates a person is already looking at.
- Be reported from public data as the system's accuracy.
- Put model code or an SDK into a Lambda package (`CLAUDE.md`: no model
  code under `src/`). It is a plain HTTPS request.
- Send a photo to Google while `rerank_mode` is off, or a query photo in
  real time before K1 is answered.
