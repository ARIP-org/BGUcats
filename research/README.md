# research/ — phase 1b, the recognition track

Everything here is the recognition research track described in
`docs/recognition-design-addendum.pdf`. It has **no dependency on phase 1a**: it
reads public datasets from disk and touches no Lambda, no S3 bucket and no
DynamoDB table, so it can be developed, reviewed and discarded independently.

Two rules keep that boundary real:

- `research/` imports nothing from `src/`.
- Research dependencies never enter the root `requirements.txt` or any
  `src/*/requirements.txt`. Torch alone would blow the 250MB Lambda package
  limit.

## Setup

```bash
pip install -r research/requirements.txt
```

For a CPU-only box, install torch from the CPU index first — it is roughly
200MB instead of 2.5GB of CUDA you will not use:

```bash
pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
```

## Running an evaluation

```bash
PYTHONPATH=research python -m catreid.evaluate \
    --dataset PolarBearVidID \
    --root research/data/PolarBearVidID \
    --variant T-224
```

`--variant` picks the backbone: `T-224` and `B-224` are for iterating in
minutes, `L-384` is the one to quote. `--max-images` subsamples for a smoke
run and is never valid for a reported number.

Results print a report and land as JSON in `research/runs/`. Embeddings are
cached in `research/.cache/`, keyed on the backbone name and the exact ordered
path list, so a cache hit can never correspond to a different split or model.
Both directories are gitignored.

## Module layout

| Module | Needs torch | What it does |
|---|---|---|
| `records.py` | no | the common `(image, identity, session)` shape |
| `splits.py` | no | session-aware and held-out-identity splitting |
| `metrics.py` | no | top-k, BAKS, BAUS, per-identity breakdown |
| `datasets.py` | no | adapters over `wildlife-datasets`, and session policy |
| `embed.py` | **yes** | MegaDescriptor feature extraction |
| `evaluate.py` | at runtime | the harness tying it together |

The split is deliberate: the logic that decides whether a number is honest is
pure Python and fully unit-tested without downloading a single weight. Only
feature extraction needs the heavy stack.

## What a session is, per source

This is the one question that decides whether a reported number is real. Every
photo in a shelter listing was taken in one sitting, against the same wall, in
the same light — split those by photo and the model is scored on matching the
wall, not the animal.

`datasets.py` therefore assigns each source an explicit policy rather than
guessing:

| Policy | Source has | Session is |
|---|---|---|
| `VIDEO` | a `video` column | one clip |
| `DATE_GAP` | a `date` column | photos of one individual within a 10-minute gap — the same rule the Telegram ingest path uses |
| `COLUMN` | an explicit listing column | one listing |
| `NONE` | none of the above | **nothing — the source cannot be evaluated** |

`NONE` does not degrade to "every photo is its own session". That substitution
is the bug, so a `NONE` source is usable for training and
`SourceDataset.for_evaluation()` refuses it outright.

**`CatIndividualImages` is a `NONE` source.** Its catalogue carries only
`image_id`, `identity` and `path` — its folders are identities, not listings,
so no capture boundary survives in the data. It can pretrain; it cannot produce
a recognition number on its own.

## Known blockers

- **Kaggle credentials.** `CatIndividualImages`, `WildlifeReID10k` and
  `CzechLynx` all download through the Kaggle API and need a token at
  `~/.kaggle/kaggle.json`. Zenodo- and URL-hosted sets such as
  `PolarBearVidID` need nothing.
- **PetFace** is gated behind a form and is non-commercial research only.
  Fine for measurement, a problem if this becomes a public app.
- **HuggingFace egress** must be allowed for the backbone weights.

## Reading the numbers

- **BAKS** — balanced accuracy on cats the system has enrolled.
- **BAUS** — balanced accuracy on cats it has never seen, i.e. how reliably it
  says "new cat".
- **auto-resolved @k=1** — the headline: how often it answers by itself and is
  right.
- The geometric mean of BAKS and BAUS is printed only so our numbers can be
  compared against published AnimalCLEF results. It is not the result; an
  aggregate hides which half is failing.

Public-data numbers validate the machinery. They are never quoted as the
system's accuracy — only BGU data measures the product.
