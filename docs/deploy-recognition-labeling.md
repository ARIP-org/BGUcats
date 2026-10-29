# Deploying `recognition-labeling` — the model in the labeling desk

A runbook for one deploy, written for whoever runs it next, by hand or with
Claude Code in the codespace.

## What is being deployed

`recognition-labeling` is `app-preprod` (what production runs today) plus:

- **research/** merged in from the research branch — never deployed, it only
  rides along in the repo.
- **The model in the labeling desk** (phase 1c, CLAUDE.md "Recognition in the
  labeling desk"): when an admin opens the Queue, the browser downloads the
  model once (~40 MB), learns the labeled cats, and records a ranked guess for
  each queue session before anyone labels it. The guess is revealed only
  after labeling. Stats gains a "Recognition model" panel: the live record,
  and a replay over labeled sessions.
- **Cat guesses in Capture**, opt-in for everyone who uses Capture: after a
  photo the phone asks "Is it one of these?" with three cats, plus "None of
  these" and "Not sure". The answer goes through the outbox and is kept
  apart from the label (the labeling desk never shows it). Stats shows
  these answers scored against the admins' labels.
- **Shared vectors**: an admin's browser uploads the vectors it computes, so
  contributors' phones download ~1 MB of templates instead of embedding
  every labeled photo.
- **API routes**: `GET /api/recognition/gallery`,
  `GET /api/recognition/predictions`, `POST /api/sessions/{id}/prediction`,
  `POST /api/recognition/vectors` (admins); `GET /api/recognition/vectors`
  and `POST /api/encounters/{id}/pick` (any member, own encounter only).
  New items are `SESSION#{id}` / `PREDICTION#{version}`, `SESSION#{id}` /
  `PICK` and `PHOTO#{id}` / `VECTOR#{version}`; nothing existing is
  rewritten. Deleting a photo now also deletes its vectors.

The bots, the process Lambda, the landing page and the data model are not
changed.

## 1. Check out and test

```bash
git fetch origin && git checkout recognition-labeling && git pull
make lint && make test
```

## 2. Build and publish the model

The export needs the research environment, never the root one:

```bash
python -m venv ~/.venvs/research && . ~/.venvs/research/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
pip install timm==1.0.30 onnx==1.23.2 onnxruntime==1.31.1 onnxscript==0.7.2 Pillow numpy
make model-export
deactivate
```

Then, with the normal environment:

```bash
make model-publish
```

It prints the manifest and "a device downloads about 39.7 MB". Publishing
first is safe: nothing loads `model/` until the new app.js is deployed.
The objects are outside Terraform on purpose (built, not committed).

## 3. Plan, and read it

```bash
make tf-plan
```

Expected, and nothing else:

| Resource | Change |
|---|---|
| `aws_s3_bucket_cors_configuration.media` | update in place: `allowed_methods` gains `GET` (the canvas must read a photo's pixels) |
| `aws_s3_object.web["recognition.js"]` | create |
| `aws_s3_object.web["app.js"]`, `["capture.js"]`, `["outbox.js"]`, `["sw.js"]`, `["styles.css"]` | update in place |
| `aws_lambda_function.admin`, `aws_lambda_function.admin_presignup` | update in place: new code (they share one zip) |

Other Lambdas may show a code update from a rebuilt zip of identical source;
harmless (see the memory note on non-reproducible zips).

**Stop if the plan shows anything to destroy or replace**, or touches
`model/` objects, Cognito, SSM, the DynamoDB table, CloudFront or API Gateway.

## 4. Apply and check

```bash
make tf-apply
```

On a phone with the installed app, as an admin:

1. Queue: a dashed line says "Model: downloading the model …", then
   "learning the cats …", then "knows N cats from M photos". The first time
   takes a few minutes; later visits are instant.
2. Label a session: a second toast says what the model had guessed.
3. Stats → Recognition model: the live record shows that session; "Replay on
   labeled sessions" gives the leave-one-session-out numbers.

4. **Share the vectors:** that first Queue visit also uploads the vectors
   ("sharing what it learned …"). Until an admin has done this once,
   contributors' guesses stay hidden — their phones have nothing to match.
5. As a collaborator (or in Capture as an admin): accept "Let the app guess
   the cat?", start an encounter, take a photo of a known cat. "Is it one of
   these?" appears within a few seconds; answer it. Stats → Recognition model
   → "Contributors" shows it once the encounter is labeled.

If the strip says "model fetch failed" or a photo fetch fails, check the
media bucket CORS rule first.

## Rollback

```bash
git checkout app-preprod && make tf-apply
```

The `model/` objects and the prediction items can stay: nothing in
`app-preprod` reads them.
