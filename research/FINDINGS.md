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
