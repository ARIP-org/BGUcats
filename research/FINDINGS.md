# Phase 1b findings — zero-shot baseline

First run of the recognition research track, 2026-10-28.

**Source:** PolarBearVidID (Zenodo, no credentials). 138,363 images, 13
identities, 1,431 clips. Session policy `video`, so every split boundary is a
real capture boundary. 9 identities enrolled, 4 held out as never-seen.

**Why polar bears and not cats.** CatIndividualImages needs a Kaggle token this
environment does not have, and — more importantly — its catalogue carries only
`image_id`, `identity`, `path`. Its folders are identities, not listings, so no
capture boundary survives in the data and it cannot produce an honest
recognition number on its own (see `datasets.py`, `SessionPolicy.NONE`). Polar
bears are uniformly coloured, which makes them the closest public analogue to
our worst case: the black cat, where coat pattern carries no signal.

Per the addendum, none of these numbers is the system's accuracy. Public data
validates machinery; only BGU data measures the product.

## 1. Backbone scale did nothing

All three MegaDescriptor variants, one clip enrolled per identity, 1,300 images:

| Backbone | Size | top-1 | top-5 | BAKS | BAUS |
|---|---|---|---|---|---|
| T-224 | 204 MB | 0.326 | 0.828 | 0.133 | 0.900 |
| B-224 | 473 MB | 0.344 | 0.784 | 0.106 | 0.908 |
| L-384 | 1.9 GB | 0.316 | 0.849 | 0.079 | 0.900 |

A 9x larger model — the variant the addendum names as the baseline to quote —
is not better than the tiny one here, and is slightly worse on top-1. Whatever
is limiting this system, it is not backbone capacity.

## 2. Enrollment diversity nearly doubled top-1

The decisive run. **Identical template budget** — 270 gallery images, 30 per
identity — differing only in how many separate captures they come from:

| 30 templates per identity | top-1 | top-5 | BAKS | BAUS |
|---|---|---|---|---|
| from 1 clip | 0.328 | 0.822 | 0.119 | 0.903 |
| from 3 clips | **0.622** | **0.948** | **0.362** | 0.903 |

The control rules out template count: going from 10 frames to 30 frames *within
one clip* moved top-1 from 0.326 to 0.328. Nothing.

**It is pose and lighting diversity across captures, not the number of frames.**

This is the Face ID "turn your head" thesis confirmed, and it sharpens the
addendum's enrollment recommendation in a way worth acting on. "Record ten
seconds panning around the cat" captures **one** session. A cat that sits still
for those ten seconds yields one pose cluster and little more value than a
single frame. The win comes from enrolling the same cat across *separate
encounters* — different days, different light, different poses.

Two consequences for phase 2:

- The enrollment UX should actively solicit re-encounters of an
  already-enrolled cat, not just one good video.
- The labeling tool's **merge** action is not only a correctness tool. Merging
  two sessions of the same cat is what builds a multi-capture template, so it
  is the main mechanism for making recognition work.

## 3. The rejection floor is expensive

BAKS sits far below top-1 everywhere (0.079–0.362 against 0.316–0.622) because
`choose_threshold` is pinned to BAUS >= 0.9. The threshold discards many
correct answers rather than risk accepting a stranger.

That is the designed bias — a wrongly-accepted cat silently corrupts the
dataset, a wrongly-rejected one costs an admin one merge — but it is not free,
and the trade-off curve should be swept and shown rather than assumed.

## 4. The per-identity spread is the real story

Best configuration, per-identity recognition rate:

```
Charlotte  0.029      Nanuq      0.400
Lloyd      0.086      Nora       0.514
Hertha     0.143      Vitus      0.543
Nana       0.257      Vera       0.571
                      Larissa    0.714
```

A 25x spread between the best and worst individual at the same threshold. An
aggregate would have reported "0.62" and hidden that two animals are
essentially never recognised. This is exactly why CLAUDE.md requires the
per-identity breakdown, and it will be sharper on cats, where the solid-colour
individuals carry the failures.

## What this answers

The addendum asked the first week of 1b for "a number, and an answer to whether
fine-tuning is even the bottleneck."

**On this evidence, fine-tuning is not the bottleneck. Enrollment is.** The
dial that needs BGU data and possibly training did not move the number; the
dial marked "needs BGU data? no" nearly doubled it. That argues for building
the multi-capture enrollment path in phase 2 before any training work, and it
means phase 3 stays CONDITIONAL on better evidence than this.

## Caveats

- 13 identities, 9 enrolled. Small.
- Polar bears, not cats. Probably pessimistic for calicos, representative for
  solid-colour cats.
- In the diversity comparison the query sets are not identical: the 1-clip run
  queries 9 remaining sessions, the 3-clip run 7. If anything that favours the
  1-clip run, which faces more varied queries — and it still lost by 29 points.
- The local-feature rerank (ALIKED + LightGlue) is not in these numbers yet.
  The addendum expects it to be the largest single gain, and it needs no labels.

## Reproducing

```bash
PYTHONPATH=research python -m catreid.evaluate \
    --dataset PolarBearVidID --root research/data/PolarBearVidID \
    --variant T-224 --sessions-per-identity 10 --frames-per-session 10 \
    --gallery-sessions 3 --unknown-fraction 0.3 --seed 0
```

Raw results land in `research/runs/` as JSON (gitignored).

---

# Round 2 — background check and the local-feature rerank

Same split as the diversity result above: T-224, 3 clips enrolled per
identity, 270 gallery images, 1,030 test photos (630 enrolled, 400 never
seen). Every variant below is a paired comparison on identical queries.

## 5. The baseline recognises the animal, not the enclosure

Mask R-CNN found the animal in 1,280 of 1,300 crops, covering on average
**38.5%** of the image — the rest is rock, grass, water and wall. Filling
everything off the animal with flat grey and re-embedding:

| | top-1 | top-5 | BAKS | BAUS |
|---|---|---|---|---|
| embedding, full crop | 0.622 | 0.948 | 0.362 | 0.902 |
| embedding, background masked | 0.595 | 0.935 | 0.287 | 0.905 |

A 2.7-point drop in top-1. Most of the signal survives removing three fifths
of every image, so round 1's diversity finding is about the animal and not an
artifact of enclosure backgrounds. Some of the drop is imperfect masks clipping
the animal, so this slightly overstates how much background was helping.

## 6. The rerank barely helps on solid-colour animals — and the guard matters

The addendum's highest-value trick did not deliver here. Where the matches land
explains why:

| LightGlue matches per shortlisted pair | same animal | different animal |
|---|---|---|
| all matches | 8.1 | 4.8 |
| matches with both ends on the animal | 1.8 | 1.1 |

**78% of all matches land on background.** On the animal itself, the
difference between the right bear and a wrong one is less than one keypoint.
White fur gives a keypoint detector almost nothing to work with.

Fusion weight, swept over stored evidence (0.0 = embedding only):

| weight | top-1 animal-only | top-1 unguarded |
|---|---|---|
| 0.00 | 0.622 | 0.622 |
| 0.05 | 0.633 | 0.621 |
| 0.10 | **0.638** | 0.617 |
| 0.20 | 0.629 | 0.608 |
| 0.30 | 0.617 | 0.610 |
| 0.50 | 0.583 | 0.565 |

- **Unguarded, it never helps at any weight.** Its extra matches are
  background, and they make things monotonically worse.
- **Guarded, a light weight gives about +1.6 points of top-1.** That gain is
  within noise for 9 identities, and the weight was chosen on the same data it
  is reported on, so the figure is optimistic.

**What this means.** Results on polar bears say nothing about patterned cats:
the addendum's claim is specifically that *coat patterns* are keypoint-rich,
and a calico should behave very differently. What it does say is that **for a
solid-colour animal — a black cat — local-feature matching will not rescue
recognition.** That is direct support for the addendum's two-stream design:
for the black cat the signal has to come from aligned face geometry (E_face),
not coat texture. It also makes the head detector and landmark alignment step a
higher priority than the rerank for exactly the cats the per-identity breakdown
says fail most.

## 7. The decision policy in numbers

At the calibrated thresholds (embedding only, accept where 90% of strangers are
rejected, "new animal" below the median stranger score), across 1,030 test photos:

| enrolled animals (630) | | never-seen animals (400) | |
|---|---|---|---|
| answered alone, right | 228 | called new, correctly | 200 |
| sent to a human, right one offered | 118 | sent to a human ("none of these") | 161 |
| sent to a human, right one missing | 37 | filed under the wrong animal | 39 |
| called new by mistake | 185 | | |
| answered alone, wrong | 62 | | |

101 confident mistakes in 1,030 photos — 62 wrong identities and 39 strangers
filed under someone. Those are the silent-corruption outcomes the threshold is
meant to suppress, and on this data it cannot get them near zero without
sending most photos to a human. Explore the trade-off interactively with
`python -m catreid.experiment --demo-out <path>`.

---

# Round 3 — first numbers on BGU cats

2026-10-29. The first run on the campus data itself, which the addendum calls
the only source whose numbers may be quoted — with the caveat that there is
very little of it yet.

**Data:** every labeled photo in production — 19 cats, 225 photos (videos
excluded), 26 sessions. Only 6 cats have more than one session, so 13 sessions
can be queried as a *known* cat; the other 13 belong to a cat with no other
session and can only test "never seen".

**Protocol:** leave one session out. Each session is hidden from the templates
in turn and ranked against every other labeled photo; a cat scores the mean,
over the session's frames, of its best template. Split by session, never by
photo. Model: MegaDescriptor-T-224 int8 (`mega-t224-int8-0ef194ac39ef`),
zero-shot, centre crop of the 1024px derivative.

| | top-1 | top-3 | top-5 | chance top-1 / top-3 |
|---|---|---|---|---|
| Python (onnxruntime, every frame) | 3 / 13 | 9 / 13 | 11 / 13 | 1/19 ≈ 5% / 16% |
| Browser (labeling desk replay, 8 frames per session) | 5 / 13 | 10 / 13 | 10 / 13 | same |

The two rows differ by frame sampling and by canvas versus PIL resizing
(browser vectors agree with Python at mean cosine 0.986, min 0.965). With 13
queries a difference of two sessions is noise; neither row is "the" number.

**Median top score:** right first ≈ 0.50–0.61, wrong first ≈ 0.42–0.44,
never-seen cat ≈ 0.41. They overlap. No threshold separates "this is her" from
"new cat" yet, so the labeling desk ranks and does not decide.

**What it says.** Well above chance — the right cat is in the top three about
three times in four — and far from auto-accept. That is the shortlist the
design always expected from v0. What it cannot say yet: anything per cat, or
anything about thresholds. Both need sessions, which is why the model now
guesses every queue session blind and the live record accumulates in the
labeling tool (CLAUDE.md, "Recognition in the labeling desk"). Round 1's
finding applies directly: most campus cats have one session, and re-encounters
are what will move these numbers.
