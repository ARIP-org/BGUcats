# Campus Cat App — working notes for Claude Code

Authoritative specs, in order of precedence:

- `docs/recognition-design-addendum.pdf` (accepted 2026-10-28) — **authoritative for
  recognition.** Amends §10 of the spec and the phase table below.
- `docs/cat-app-design-spec.pdf` (v2 draft) — authoritative for ingest, storage,
  processing and security.

Read both before non-trivial work. For **how** the project is built, deployed
and worked on — accounts, environments, repos, people — `docs/ROADMAP.md`
is the plan; read it before any infra, CI/CD, repo-layout or access work.
This file is the short version of the
constraints that are easy to violate by reflex. `docs/notes.md` is the
traps behind them, each with where its story is: read it before touching
DynamoDB reads, the pipeline or the agents, and add to it.

**The app from the prototype is being built** (the owner, 2026-11-12):
feed, posts, polls, friends, moderation and re-ranking, for TestFlight,
behind the `social` flag. `docs/app-plan/` is the plan, and its
`08-milestones.md` says what is built; read its `README.md` before any
work on it. The plan lifts none of the rules below by itself: the pull
request that lifts a rule edits that rule here, in the same change.

The addendum supersedes the spec's "no machine learning of any kind" in
phase 1: a frozen recognition model runs in the browser today (1c below). It
ranks; it never decides.

**`main` is staging; production is the latest `v*` tag.** How changes reach
them: "Workflow" below.

## What this project is

A mobile app for identifying, naming, and tracking campus cats — starting with the
~50 on the BGU campus, with an architecture that is deliberately not limited to
them. Browse / Identify / Name. Cats are admin-curated; there is no automated
"is this a campus cat" validation.

## The one thing to understand

**This is Face ID, for cats.** Not a classifier with one output per cat — a
detector, an aligner, an embedding network trained with metric learning, cosine
similarity against an enrolled template, and a threshold with a reject path.

The old framing ("a kNN over embeddings with a human picking from a short list"
*versus* "a model that really recognizes the cat") described one system at two
confidence levels, not two systems. Only the decision step changes as data
arrives:

| | Face ID | Cats v0 | Cats v2 |
|---|---|---|---|
| Enroll | turn your head | pan the camera around the cat | same |
| Match | embedding vs. template | embedding vs. template | same |
| Decide | accept, else passcode | accept, else **pick from 3** | accept, else pick from 3 |

The architecture shipped next month is the architecture shipped at the end. A
candidate list is not a placeholder for real recognition; it is real recognition
at a lower confidence threshold.

**Headline metric:** the fraction of queries auto-resolved at k=1 above
threshold. It starts near zero, ends near one, and every value in between is a
shippable app.

### What changed from the original spec

The spec assumed recognition had to wait for BGU data. It does not. Public
cat-identity datasets and animal-specific pretrained models are good enough to
build and measure the whole recognition path **now**, against real numbers,
before the first BGU photo is labeled. Generic embeddings (CLIP, ImageNet,
DINOv2) do cluster by category rather than individual — but models pretrained
for animal individual discrimination exist, and MegaDescriptor is one.

## Phases

| Phase | Status | Scope |
|---|---|---|
| 1a Collection + labeling infra | LIVE | ingest, storage, processing, admin labeling, Capture |
| 1b Recognition research track | ROUNDS 1–2 DONE, PARALLEL | public datasets, eval harness, zero-shot baseline. Finding: enrollment diversity, not backbone size, is the lever (`research/FINDINGS.md`) |
| 1c Measure on BGU data | LIVE since 2026-10-29 | the frozen v0 model guesses every queue session, shown on its card; replay over labeled sessions; "Who did you meet?" after each encounter in Capture. No guess was recorded before the 2026-10-29 null-`catId` fix. Shared vectors appear after an admin first opens the Queue |
| 2 Enrollment + burst-query UX | NEXT | video enrollment, multi-frame query, frozen v0 weights. Re-encounters of known cats are what move the numbers |
| 3 Fine-tuning on BGU data | CONDITIONAL | only if 1c numbers justify it |
| 4 Read path + mobile app | STARTED 2026-11-12, BEHIND A FLAG | public API, browse UI, voting; and the feed, friends, moderation and re-ranking of `docs/app-plan/`. Built milestone by milestone (`08-milestones.md`), on in staging, off in production until L3 |

**1b has no dependency on 1a.** It reads public datasets from disk and touches no
Lambda, no S3 bucket, and no DynamoDB table.

**1c is where they meet**, deliberately small: the 1b model, exported to ONNX,
runs in the browser — on every card in the labeling desk, after each encounter in Capture — and is
scored against the labels admins give anyway. It decides nothing — see
"Recognition in the app" below. First BGU numbers (2026-10-29, 19 cats): right cat first
on 3–5 of 13 sessions, in the top 3 on 9–10 of 13 (`research/FINDINGS.md`,
round 3).

**The risk, stated once:** the ML track is more fun than the ingest track, and if
it eats the ingest track there is never any BGU data — the one asset here that
cannot be downloaded. 1a stays the priority; 1b is what happens when 1a is
blocked on someone else.

## Workflow

- **`main` is what staging runs; production runs the latest `v*` tag**
  (since 2026-11-10; before that a merge deployed production). There are
  no long-lived feature or "preprod" branches. The old stack
  (`admin-labeling-tool` → `app-preprod` → `recognition-labeling`) was merged
  into `main` on 2026-10-29 and survives as `rollback/*` tags only.
- **Work on a short-lived branch**, one change per branch, and open a pull
  request to `main`. CI runs lint, tests and `terraform plan` for both
  accounts on it (staging: what the merge deploys; production: what the
  next promote would). **Two lanes** (the owner changed the `main`
  ruleset on 2026-11-23): a pull request that touches no owner path
  (`.github/CODEOWNERS`) merges to staging by itself once CI and the
  reviewer's check (`review`, `.github/workflows/claude-review.yml`)
  pass; one that touches an owner path, or that the reviewer sends up,
  waits for the owner, who reads its plans and merges. The reviewer
  sends up only a short list (`docs/agents.md`, "The reviewer, and the
  two lanes"), and its script, not its judgment, sends up every change
  to an owner path (since 2026-11-23, when one merged by itself: the
  ruleset alone had not held it). The same script takes a pass back when
  any other check on the commit is red or still running, the iPhone
  app's Mac check above all, which is not part of CI (since 2026-11-24,
  when a pull request merged with that check failed and `main` could not
  be built for TestFlight). Neither lane reaches production: that is the
  owner's tag.
- **One commit per file** (the owner, 2026-11-24: "I want to see more
  commits"). A pull request's commits each change one file, and each
  message says what changed in that file and why. They come in an order
  that reads: the code, then its tests, then the docs. A commit in the
  middle need not pass the tests alone; the pull request as a whole
  does, and that is what CI checks. A file made by a script goes with
  the file it is made from (`docs/privacy-data.md`), and a merge of
  `main` is one commit. This holds for sessions and for the builder
  (its prompts in `.github/workflows/claude-fix.yml`).
- **Merging deploys staging; a tag promotes.** A push to `main` runs
  `.github/workflows/deploy.yml`, which plans and applies `infra/main` to
  the staging account under a GitHub OIDC role and marks the commit
  `deployed/staging`, once a smoke test has put one made-up photo through
  staging's pipeline (`scripts/smoke_staging.py`). Production gets a commit
  only when the owner tags it `v*`, and only if it is on `main` with that
  mark: the same job, the same steps, without the smoke test. Only the owner creates those tags (a tag ruleset); Claude never
  does. Runbook, promoting, post-deploy checks and rollback: `docs/deploy.md`.
- **The iPhone app is built on request, not by a merge**
  (`.github/workflows/ios.yml`, since 2026-11-11). The owner starts it from
  `main` (*Actions* → *iOS* → *Run workflow*); Claude never does. What it
  uploads is the Swift app (since 2026-11-23). A macOS
  runner costs ten times a Linux one, so a pull request gets the simulator
  check only when it touches `native/`. The App Store Connect key lives in
  the `testflight` environment, which admits `main` alone.
  `docs/deploy.md`, "The iPhone app".
- **Never deploy by hand and never push to `main`.** No `terraform apply`,
  `make tf-apply` or `make site-invalidate` on `infra/main` from a codespace
  or a Claude session. The codespace holds no AWS keys; credentials come only
  from `aws sso login` (`docs/codespaces.md`).
- **AWS commands from a Claude session** (owner's decision, 2026-11-07):
  read-only (`*-ro`) by default. With the owner signed in and asking for a
  specific job, Claude may also run write commands with the `*-admin`
  profiles; that is how step 9 was done. Never in place of a deploy: a
  change to what `infra/main` describes still goes through a PR. Never a
  write to production's table or media bucket unless the owner names it.
  Since 2026-11-10 this includes applying `infra/bootstrap`
  (`bootstrap-apply.sh`) and `infra/org` (`org-apply.sh`) when the owner
  asks; `aws sso login` always needs `--profile` (there is no default one).
- **Production has an account of its own,** `sasha-bgucats-prod`
  (`395591097129`), named in one file: `infra/main/backend/prod.hcl`.
  It has been production since the cutover on 2026-10-30 (app
  `https://d1m4aukbm35e12.cloudfront.net/`, Cognito `bgucats-app`).
  **Staging** is `bgucats-staging` (`586943192664`, created 2026-11-07,
  `infra/main/backend/staging.hcl`): the same Terraform with
  `environment = "staging"`, no Telegram bot, its own Google client, never
  real contributor photos. Being set up (`docs/ROADMAP.md`, Phase 2b).
  `851725214678` is the organization's management account and has run
  nothing since step 9 (`docs/MANUAL_STEPS.md`, 2026-11-07): Organizations,
  Identity Center, billing, one DynamoDB backup of the old table, and since
  2026-11-10 the guardrails of `infra/org` with their state bucket. The old
  deployment and the old copy of the data are gone; there is no way back
  through it. Never deploy there. Every hand-run AWS
  command names its SSO profile (`bgucats-prod-ro`, `bgucats-prod-admin`,
  `bgucats-staging-ro`, `bgucats-staging-admin`, `mgmt-ro`, `mgmt-admin`);
  `infra/scripts/aws-guard.sh` refuses the wrong account (a staging profile
  means staging) and leftover access keys.
- **The owner orchestrates; Claude writes the code and the infrastructure**
  (2026-11-07). Never add a new kind of AWS resource quietly: CI fails a
  plan that holds a kind not in `infra/main/allowed-resource-types.txt`,
  the deploy role must be widened first (bootstrap), and every service the
  project does not use is denied by SCP even to admins (`infra/org/scp.tf`).
  Adding a line to either list is the owner's decision, never a fix.
  What Claude may and may not do, and how that is enforced rather than
  promised: `docs/ROADMAP.md`, Phase 2c "Guardrails" and 2d "Claude in CI".
- **Spending is limited from outside the accounts** (`infra/org`, applied
  from the management account, 2026-11-10). Each member account: $10
  emails, $20 attaches an SCP that freezes every change (the app keeps
  running), $40 one that stops the app's API (data and static pages stay).
  AWS detaches both at the start of the next month; lifting one sooner is
  in `docs/deploy.md`, "When a budget action fires". The table stays
  `PAY_PER_REQUEST` and Lambdas stay small (`scripts/check_plan.py`):
  nothing in AWS can enforce those two.
- **The app says when it breaks** (`infra/main/alarms.tf`, 2026-11-10): an
  email to the bootstrap admin on any Lambda error or API 5xx, in each
  account. What each alarm means: `docs/deploy.md`, "When an alert email
  arrives". A new Lambda is added to `alarmed_functions` in the same PR.
- **Four things CI does not do:** `infra/bootstrap` (the state backend and
  the GitHub roles; it cannot deploy itself), `infra/org` (the
  organization's guardrails; no GitHub role exists in the management
  account), `make model-publish` (needs torch) and
  `infra/scripts/set-secret.sh`. Claude may apply the first two in the
  owner's session when asked. A secret's value is typed by the owner only.
  All are in `docs/deploy.md` and `infra/README.md`.
- **No secret value in Terraform.** The bot's secrets (SSM), Apple's push
  key (SSM, since B9) and the Google OAuth client (Cognito) are set with
  `set-secret.sh`; Terraform only names them. Anything it manages lands in the state, which every PR's CI run can
  read. Never add a secret `variable`, `aws_ssm_parameter` value or
  `aws_cognito_identity_provider` back.
- **The repository is public** (since 2026-11-22: its runners are
  free). No real person's name, address or photo, and nothing private,
  in a file, a commit message, an issue, a pull request or a log. Agents
  take work only from people who can push: an issue labeled `ready` by
  one of them is built with no person reading it first, and `approved`
  is the owner's (`docs/agents.md`, "The builder's queue" and "When the
  repository is public").
- **Rollback is `git revert`** of the merge commit, merged like any change.
- **Update the docs in the same PR** as the change: `docs/deploy.md` when the
  deploy changes, `docs/app-backlog.md`, `research/FINDINGS.md`, and this
  file when a constraint or a phase changes.

## Hard constraints

### Collection path (spec §10)

- **Browse, voting and polls only behind the `social` flag** (since F4 of
  `docs/app-plan/`, 2026-11-12). The member app lives under `/api/v1/`
  (`src/app/`, its own Lambda) and answers 404 while the account's
  `settings.social` is false: production, until the app opens (L3);
  staging has it on. With it off, the desk, Capture and the bot are
  exactly what they were. Capture's cat guesses after each encounter
  (1c) are shown to signed-in users and admins, never to the public, and
  measure the "pick from 3" loop; see "Recognition in the app" below.
- **Do not attach Lambdas to a VPC.** No NAT gateway, no subnets, no security
  groups. Lambda outside a VPC has full internet access; S3, DynamoDB and the
  Telegram API are all public endpoints. (§8.1)
- **The ingest handler must not process images.** Fetch, store, record, respond.
  Telegram times out webhooks and a slow handler means lost submissions. All
  processing is triggered by the S3 event.
- **Use the exact key formats in spec §6.2 and §6.3.** The ID-as-join-key
  property depends on them.
- **Every write is idempotent on the ULID.** Write order: DynamoDB record as
  `pending`, then S3, then flip to `unlabeled`. A record marked ready whose
  object never landed is a silent failure that surfaces months later.
  A `pending` record sits on GSI2 as `STATUS#pending` from the start, and
  Stats → Bot health lists any still pending after an hour. A failed or
  timed-out bot fetch (`OSError`, not just `URLError`) leaves the record
  pending and asks the sender to send it again; neither platform redelivers
  an acknowledged update.
- **The admin labeling tool is in scope for 1a.** Queue view, session grid,
  merge and reject actions. A 2,000-image backlog never gets climbed.
- **Prefer boring, inspectable choices.** Portfolio project; every decision
  should be explainable in an interview.

## The app (web/) — labeling desk and Capture, one PWA

The admin tool is installable ("Add to Home Screen") and is also how invited
collaborators photograph cats. It **complements** the Telegram bot, never
replaces it: the bot keeps working unchanged, and the app is a second
channel (`channel = "app"`) into the same table, bucket and process Lambda.
**There is no WhatsApp bot** (removed 2026-10-30, irrelevant to the
product). Its old sessions and photos stay in the table with
`channel = "whatsapp"`, and the app still labels them.

- **Two roles, `user` and `admin`** (the owner's decision R1, 2026-11-12;
  `src/common/admission.py`). `admin` = everything. `user` = Capture
  (with the cat guesses), browsing the cats and, behind the `social`
  flag, the member app; no queue or labeling, no deleting, merging,
  creating or renaming cats, no stats or people. A collaborator is a
  user: `role = collaborator`, written before that day, is read as
  `user`, and the people screen writes `user`. **No role field means
  admin**, so the Terraform bootstrap item and `make admin-add` keep full
  access. The API enforces this per route (`ROUTES` in
  `src/admin/handler.py`, last column); the UI only hides what would be
  refused.
- **Who may sign in is the account's sign-up policy** (`settings.
  signup_policy`): `allowlist` (an `ADMIN#{email}` item, as before; staging,
  and production until L3), `domain` (also any address at BGU's domains)
  or `open`. Checked by the Cognito pre-sign-up trigger and again by both
  APIs on every call, so taking someone off the allowlist or tightening
  the policy shuts them out at once.
- **An encounter is a Session opened deliberately** ("Start an encounter" …
  "Done"), so it is an identity cluster by construction.
- **Same write order as the bots, split across calls:** record as `pending`
  (`POST /api/encounters/{id}/media`) → the phone uploads to
  `raw/{sessionId}/{photoId}.{ext}` with a presigned POST that pins key, type
  and size → `POST /api/photos/{id}/complete` confirms the object and sniffs
  its magic bytes before flipping to `unlabeled`. The status flip is
  conditional on `pending`, so a duplicate verdict from the process Lambda
  is never overwritten.
- **IDs are ULIDs minted on the phone**, so the offline outbox (web/outbox.js)
  can retry anything and land on the same records.
- **The outbox writes a photo's bytes once, never again.** Its state lives
  in its own IndexedDB store, because Safari can refuse to re-store a Blob
  read back from IndexedDB. Every request has a timeout. One photo's failure
  never holds up the rest, and the screen says why it is retrying. An
  encounter reaches the API with its first photo, so empty ones are never
  written. Before 2026-10-29, 48 photos stalled for an hour without a word.
  A photo never goes before its encounter: a pass of the queue reads the
  photos first and the encounters after (`tests/web/test_outbox_order.py`;
  the other order lost a post now and then until 2026-11-23).
- **Location comes from the phone's GPS at the moment of capture**, with its
  accuracy (`locationSource = "app-gps"`, `locationAccuracyM`), rounded to
  3 decimals like everything else. GPS takes seconds and the first photo
  does not wait for it: an encounter with no place takes the one the
  phone sends a moment later (the outbox's `placeEncounter`, since
  2026-11-13), and one that has a place never changes it. A photo the
  client marks `origin = "gallery"` (picked from the phone's gallery,
  #108) keeps no place at all: not the one sent with it, not its EXIF's,
  and it never places its encounter; the member API shows it as not
  made on the spot.
- **Installed app only.** A browser tab gets the install page (web/install.js:
  what the app is for, how to use it, how to install it — Hebrew, English,
  Russian, Arabic) instead of the app. It is a front door, not security: the
  API still checks every call. `?browser` opens the app in a tab anyway, for
  when the installed app cannot sign in on some phone.
- **The iPhone app is being rewritten in Swift** (the owner, 2026-11-22;
  `docs/ROADMAP.md`, 2g). "One codebase, never a platform branch" is
  lifted for the member app: the Swift app is its own code against the
  same member API, the web member app (`web/social/`) is frozen to fixes
  and retires when the Swift app has its screens, and the desk and
  Capture stay web.
- **TestFlight gets the Swift app, unfinished** (the owner, 2026-11-23:
  ship it as soon as possible, in the same app and not a second one, so
  its flaws and the system's glass are seen and fixed on the phone). A
  tab whose screen is not built says so, and the home-screen app has that
  screen meanwhile. Every pull request to it archives it exactly as the
  upload does (`scripts/ios_archive.py`, the `swift` job); a screen comes
  with its picture from the simulator. `native/swift/README.md` has its
  rules.
- **The app it replaced is `web/`, packed** (`native/`, Capacitor,
  TestFlight's from 2026-11-11 to 2026-11-23; `docs/ROADMAP.md`, 2e).
  Nothing uploads it now; its code and its pull-request check stay until
  the Swift app has been on the owner's phone, and what follows is how it
  works. One codebase for it: `web/` keeps no build step, and the only thing it knows is
  `isNative()` (install.js). The app carries a copy of `web/` made at build
  time (`scripts/native_bundle.py`), so a merge reaches it only with a new
  build, and its API is at `config.apiBase`, not at the page's own address.
  It counts as installed and registers no service worker. It never loads
  `web/` from the server instead. It signs in through iOS's own sign-in
  sheet (`native/plugins/web-auth`), never inside the web view: Google
  refuses that. Cognito answers at `org.arip.bgucats://signin`. To the
  packed pages the API and the bucket are other origins, so the API has a
  CORS configuration (any origin: API Gateway takes only `http(s)` or `*`,
  and every call still needs its token). A preflight carries no token, so
  `OPTIONS` has a route without the authorizer, and API Gateway hands it
  to the Lambda: each handler answers it 204 before anything else
  (`preflight` in `src/common/api.py`; a 401 there is "Load failed" on
  every call, as it was until 2026-11-13). The media bucket lists
  `capacitor://localhost`. It opens on the member app (`frontDoor = "app"`
  in the packed config, since N1). The model comes from the site's
  `/model/`, which CloudFront answers with an AWS-managed CORS policy (no
  new resource kind), and is kept in IndexedDB, since no service worker
  caches it there.
- **A launch is never a blank screen** (since 2026-11-14;
  `tests/web/test_member_start.py`). `app.html` carries its own
  "Loading…" in the page, which after twelve seconds names the step it
  is on and offers "Try again" and "Reset the app on this phone" (the
  service worker and its kept files only: sign-in, the upload queue and
  the model stay). Each step of the start has a time limit and a failure
  says where. The site's root sends an installed app to its front door
  before fetching anything else of the desk. With no signal the app opens
  with the account it last read on this phone (the same sign-in only)
  and reads it again when the signal is back; a phone that has never
  read it says it cannot start.
- **The phone keeps what the app was doing** (since 2026-11-14;
  `app.html`, `web/social/trail.js`, `tests/web/test_member_appinfo.py`):
  the last eighty lines, in localStorage. The start's steps, the capture
  flow, what it asked the phone for, the model's stages, failures nobody
  caught, and every time the screen stopped answering. Profile has "App
  info" to read and copy it. A line says what happened, never who: no
  name, no address, no token, nothing anyone wrote. A bug on someone's
  phone is asked for with "copy App info", not guessed at.
- **What the phone kept is checked before it is used.** The capture flow
  is kept between launches; a kept flow that is not whole is dropped, a
  change with no flow open changes nothing, and a page that cannot be
  drawn closes the flow and says so instead of leaving the app out of
  reach (`tests/web/test_member_flow_kept.py`). A piece of a flow kept
  by a late tap froze the owner's home-screen app until 2026-11-15.
- **Sign-in always shows Google's account chooser** (`prompt=select_account`,
  which Cognito forwards only with managed login — `managed_login_version = 2`
  in cognito.tf). Sign-out only forgets the app's tokens and stays in the
  app; a sign-in that the allowlist refuses forgets its tokens too, so nobody
  is stuck retrying the wrong account.
- **The service worker (web/sw.js) is network-first** and never touches
  `/api/`, photos or other origins — the distribution's no-caching rule still
  means a deploy reaches everyone on their next load. The one exception is
  the content-addressed `/model/{version}/`, cached first (see 1c below).
  A page (never a script) waits four seconds for the network and then
  opens from the kept copy, each page under its own name; both pages
  register the worker (`tests/web/test_service_worker.py`, the only tests
  that run it).
- **Uploads keep going after the app is left, where the browser allows
  it.** Chrome on Android has Background Sync: the outbox registers it with
  every photo and when the app is hidden, and the service worker runs the
  same three steps on the same IndexedDB queue. The app's tokens are copied
  to IndexedDB (`bgucats-auth`), because a worker has no localStorage. An
  iPhone has no such API: Safari suspends a hidden app within seconds, so
  uploads move only while it is open. The app keeps the screen awake while
  files are waiting (Wake Lock) and says so on screen. Three uploads run at
  once.
- **The member app is `app.html` beside the desk** (`web/social/`, since
  E0 of `docs/app-plan/`): Preact and htm and the Inter font from
  `web/vendor/`, pinned by checksum and never from a CDN; every colour in
  `web/tokens.css` (four themes, from the prototype); every string through
  `t()` and `web/i18n/en.json`; only logical CSS properties
  (`tests/web/test_client_rules.py`). Hebrew, Russian and Arabic are
  drafts no speaker has read (`tests/web/test_languages.py` holds each
  to English's keys); which languages the profile offers is the
  account's `languages` setting, English alone in production. Signing in, the API client and the
  photo-address cache are shared from `web/lib/`. Which page opens first
  is `frontDoor` in `config.json` (`app` on staging since 2026-11-13,
  `desk` in production until L3); `?desk` keeps the desk, and each page
  links to the other. Staging's site is `web/` with `web-staging/` laid
  over it (`infra/main/web.tf`): its home-screen icon says "BETA". Its capture flow (E3, `web/social/scan.js`) writes through the
  same outbox as Capture, in the same write order, and adds the proposal
  and the post after the photos. `infra/main/web.tf` uploads
  every file under `web/`, so a new file needs no Terraform.
- **Caching lives in web/lib/ (since E0; app.js before), not the service
  worker.** Presigned photo URLs
  carry a long `response-cache-control`, and the app reuses the first URL it
  saw for each object until just before it expires (`stablePhotoUrl`).
  Without that, every new signature is a cache miss and every screen
  downloads every photo again. Screens reuse their GETs for 15 s, then show
  the last answer at once and redraw only if a refresh changed something
  (`cachedGet`). Any action clears that memory.

- **The screens have tests** (`tests/web`, since 2026-11-10): a headless
  Chromium at a phone's size opens the real `web/` against the real API and
  process handlers (and, since B3c, the member API and the events Lambda,
  fed by a stand-in for the table's stream), with DynamoDB and S3 mocked
  on localhost (`tests/web/localapp.py`). No AWS, no real photo. A change to a screen
  comes with its test, and `make screenshots` leaves a picture of every
  screen in `build/screenshots/`; CI keeps them with each run. `make
  local-app` runs the same app to click through by hand. Sign-in and the
  recognition model are the two things it fakes or leaves out.

### Recognition in the app (1c — web/recognition.js)

Two uses of one model, kept apart on purpose. The admin-side guess
measures **the model**. The contributor's answer, scored against the
admin's label, measures **the product loop** ("pick from 3"), and earns its
place by what only a person next to the cat can do: take a better photo
when unsure, and come back to cats already met.

#### In the labeling desk (admins)

- **Shown, and recorded first.** The model ranks every known cat for each
  queue session and the ranking is recorded (`POST /api/sessions/{id}/prediction`)
  *before* anyone labels it. Its top three are shown on the session card
  ("Model's guess", with cosine similarity) and at the top of the picker,
  where one tap labels. Until 2026-10-29 the guess was hidden until after
  the label, to keep labels independent of it. The admin decided it does
  not sway their judgment and wanted it in plain sight. The model's score
  is still honest, because its guess is fixed before the label. Labels made
  since then are no longer independent of the guess. Tapping a guess on the
  card only opens the picker: a guess is never a label by itself.
- **A guess made after the label is not a measurement.** The write is one
  DynamoDB transaction conditional on the session having no `catId` — absent
  *or null*: every session is written with `catId = null`, and until
  2026-10-29 `attribute_not_exists` alone refused all of them as labeled; the
  first guess per model version wins (`SESSION#{id}` / `PREDICTION#{version}`,
  listed through GSI2 `ENTITY#PREDICTION`). A merge counts as a label.
- **It only ranks.** No auto-accept, no "new cat" verdict, and the manifest
  ships `"thresholds": null`: on BGU photos the top scores of right guesses,
  wrong guesses and never-seen cats overlap. Thresholds are earned from the
  live record, not borrowed from polar bears.
- **The browser does the ML; the API stays boring.** The API hands out the
  labeled photos (`GET /api/recognition/gallery`) and stores and joins
  guesses and contributor answers (`GET /api/recognition/predictions`). No
  model code under `src/`, no torch near a Lambda. These are ADMINS; the
  shared-vector read and a contributor's own pick are the only member routes.
- **The model is published, not deployed by Terraform.** `make model-export`
  (research env) then `make model-publish` uploads `model/{version}/` to the
  admin web bucket — model, and ONNX Runtime Web self-hosted from a
  sha512-checked npm tarball, never a CDN in a page holding sign-in tokens —
  and writes `model/manifest.json` last. The version is a hash of the model,
  so sw.js caches `/model/{version}/` cache-first; the manifest is never cached.
- **Pixels need CORS.** The media bucket allows GET from the app's own origin
  only, so a canvas can read a presigned photo. Every read still needs a URL
  the API signed.
- **Cost:** ~40 MB per device per model version (29.5 MB int8 model + 10 MB
  runtime), ~150–250 MB of memory while running. AWS cost is cents: storage
  and CloudFront egress.
- **Starting the model stops the thread it starts on for seconds.** The
  desk starts it on the page, in the background of a screen nobody is
  tapping. The member app must not: its capture flow runs the model in
  the runtime's worker (`createRecognition({ worker: true })`) and starts
  it after the screen is drawn, never inside the tap that opens it. That
  tap froze the owner's iPhone until 2026-11-14
  (`tests/web/test_member_model.py`).

#### Shared vectors

- **Embedded once, by an admin's browser.** After learning the labeled photos
  it uploads their vectors (`POST /api/recognition/vectors`, ADMINS, item
  `PHOTO#{id}` / `VECTOR#{version}`, listed through GSI2 `VECTOR#{version}`).
  Every phone — and every other admin device — downloads them
  (`GET /api/recognition/vectors`, any member, paged) instead of embedding
  the gallery: ~4 KB per photo, about 1 MB today. The Queue runs the model
  even when it is empty, so any admin's visit keeps the shared copy current.
  The admin role needs `BatchWriteItem` for this, and `ConditionCheckItem` for
  the blind-guess transaction. Both were missing until 2026-10-29.
- **Same pipeline on both sides.** Gallery and query vectors both come from
  the browser (canvas resize, the same ONNX graph), so they agree; Python
  vectors differ slightly (cosine ~0.986) and are never mixed in.
- Deleting a photo deletes its vectors. Vectors are only templates while the
  photo is labeled.

#### In Capture (everyone: contributors and admins)

- **On unless turned off** (since 2026-10-29; it used to be opt-in). The
  model, about 40 MB, downloads once in the background from the first visit.
  A phone in data-saver mode is asked first. "Turn off" is on the Capture
  screen. A missing or failed model never blocks or slows an upload.
- **Guessed while shooting, asked after Done.** Each photo is embedded in
  the background as it is taken (up to 8 per encounter; the vectors stay in
  memory). "Done" opens the encounter's result, "Who did you meet?", with
  the photos and their upload progress. It asks "Is it one of these?" over
  three cats with covers and "met N×" (admins see the similarity),
  "Another cat…" (every cat, the model's order first), "A cat that isn't
  here", "Not sure", "Take more photos" and "Skip". The encounter stays open
  until then, so an unsure guess can still become a better photo. The
  ranking is kept with the encounter, so a reload lands back on the result
  screen with its guess. The first guess alone is right about one time in
  three; the three about three in four.
- **The answer is kept apart from the label.** It rides in the outbox with its
  encounter (`POST /api/encounters/{id}/pick`, own encounter only, latest
  answer wins, item `SESSION#{id}` / `PICK`). The labeling desk never reads
  it, so the admin labels without seeing the contributor's answer. "Your
  recent encounters" later shows "you: X ✓/✗" and "model: Y ✓/✗" against
  the label.
- **The reward is the re-encounter.** The answered screen says "Encounter
  #N with this cat" — re-encounters are what research/FINDINGS.md found
  matter most. "Next cat" starts the next encounter straight away.
- **Replay** (Stats → Recognition model) re-runs the ranking over labeled
  sessions, each hidden in turn — split by session, never by photo. Same
  scoring code as the live record (`summarize` in recognition.js).

### Research track

- **`research/` imports nothing from `src/`.** No boto3, no AWS, no Lambda
  handler code. It must stay independently reviewable and discardable.
- **Research dependencies never enter `requirements.txt` or `src/*/requirements.txt`.**
  Torch alone would blow the 250MB Lambda package limit. `research/requirements.txt`
  is a separate world.
- **No softmax classifier over our cats, ever.** It cannot add cat #51, cannot say
  "I don't know this one", and needs retraining per cat. It would feel like
  progress and is a dead end. This is permanent, not "for now" — it is also what
  makes scaling past one campus possible at all.
- **No depth sensor.** TrueDepth and LiDAR are the tempting analogue to Face ID's
  IR projector and are a trap: wrong range, wrong subject cooperation, for a cat
  two metres away under a bush.
- **No nose-print biometrics in v1.** The published work is thin — one 70-cat,
  700-image study — and it needs a cooperative close-up we will never get.

## Recognition architecture

```
query burst (1-2 s of frames)
  → cat detector (body bbox)
  → head detector + 48 facial landmarks → align
  → two embeddings:
        E_face   aligned head crop   — geometry, facial markings
        E_coat   body crop           — coat pattern and colour
  → fused similarity vs. enrolled templates → ANN top-50
  → local-feature rerank of those 50 only (ALIKED / DISK + LightGlue)
  → accept / top-k / "new cat"
```

- **Two streams, because the failure mode is solid-colour cats.** Coat pattern
  carries nearly all the signal for a calico and nearly none for a black cat;
  face geometry carries it for the black cat. A single whole-image embedding
  blends the two *and* picks up the background.
- **Local-feature reranking is the highest-value trick available, because it
  needs no labels at all.** Too slow over the whole gallery, so it only ever
  reranks the ANN top-50.
- **Templates, not centroids.** Store several embeddings per cat. Frontal and
  profile views sit far apart in embedding space, and averaging them produces a
  vector that matches neither.
- **Enrollment is the Face ID insight:** *record ten seconds panning around the
  cat.* 30–100 frames, identity guaranteed, pose and light varied, with a free
  quality filter. This is the session-as-identity-cluster idea extended to UX.
- **Mirror it on the query side: identify a burst, not a frame.** Embed every
  frame of a 1–2 second capture and aggregate the ranked lists.

### Three axes, improving independently

| Axis | v0 | Later | Needs BGU data? |
|---|---|---|---|
| Embedding quality | zero-shot MegaDescriptor | fine-tuned on BGU + public | yes |
| Enrollment richness | multi-frame video template | same | no |
| Decision policy | top-5 human pick | top-1 auto-accept + reject | calibration only |

The right first baseline is **not** zero-shot DINOv2. It is MegaDescriptor-L-384
plus a local-feature reranker — someone else already paid for the expensive
pretraining.

## Open-set is the hard requirement

"Is this a cat I know, or a new one?" is harder than ranking, and it is the
actual product question.

- Score on similarity to the best-matching enrolled template.
- **Calibrate the threshold on held-out identities, never held-out photos.**
  Identities the model has never enrolled are the only honest proxy for cat #51.
- **Report knowns and unknowns separately** — balanced accuracy on each (BAKS and
  BAUS). An aggregate hides which half is failing.
- **Bias the threshold toward false "new cat" verdicts.** That costs an admin one
  merge, and the labeling tool already has a merge action. The opposite error
  silently corrupts the dataset and surfaces months later.

## Evaluation

- **Split by session, never by photo.** Two frames from one burst are
  near-identical; one in train and one in test makes reported accuracy fiction.
- **One listing or one source folder counts as one session.** Every photo in a
  shelter listing was taken in one sitting, against the same wall, in the same
  light. Same rule as above, different vocabulary — and the easiest way to
  accidentally report fiction when using public data.
- **Open-set from the first run.** Hold out whole identities, not just photos.
- Report top-1 and top-5 separately, plus a per-cat breakdown — an aggregate
  hides that every error is a black cat.
- **Public-data numbers are never reported as the system's accuracy.** Shelter
  portraits against a studio wall are a different world from a cat under a bench
  at dusk. Public data validates the machinery; only BGU data measures the product.

## Data model essentials

- **ULID** is the join key everywhere: DynamoDB PK, S3 key prefix, later the
  vector ID. Chosen over UUIDv4 for lexicographic time-ordering.
- **Session = one encounter with one cat = a guaranteed identity cluster.** Same
  submitter within a 10-minute idle window joins the same session; Telegram media
  groups always map to one session.
- S3 layout:
  ```
  raw/{sessionId}/{photoId}.{ext}        original, write-once, never mutated
  derived/{photoId}/thumb-256.webp
  derived/{photoId}/medium-1024.webp
  exports/{datasetVersion}/manifest.json
  exports/{datasetVersion}/images/...
  avatars/{userId}/{avatarId}.jpg        a member's profile photo (the app, B1b)
  ```
- Single DynamoDB table, three GSIs: photos-in-session, labeling queue by
  status, photos-of-a-cat for export. Every key it holds:
  `docs/data-model.md`, kept true by a test; a pull request that adds a
  key adds it there, and says in `scripts/privacy_table.py` what it holds
  about a person (`docs/privacy-data.md` is that script's output: the
  App Store's privacy answers, held to the code by a test).

## Processing rules

- pHash + SHA-256. Near-duplicates are **flagged, not silently dropped** — a
  burst of similar frames is legitimate.
- An object under `raw/` with no photo record is skipped, not processed:
  the write order means it did not come through a bot or the app.
- Derivatives: 256px thumbnail, 1024px medium, WebP.
- EXIF: extract capture timestamp and GPS into the record, then **strip all EXIF
  from every derivative**. Store location rounded to ~100m — it must not reveal
  precisely where a contributor was standing.

## Data sources

| Tier | Source | Role |
|---|---|---|
| 1 | CatIndividualImages (509 ids / 13,021 imgs, CC BY 4.0) | best single fit |
| 1 | HelloStreetCat (69 cats / 2,796 imgs) | closest domain match — uncooperative street cats |
| 1 | PetFace (257k ids) | has an unseen-individual benchmark; **non-commercial research only**, gated |
| 1 | WildlifeReID-10k | eval harness, cross-species pretraining |
| 1 | CatFLW + its detector | the alignment step |
| 2 | Petfinder / RescueGroups APIs | one listing = one individual with several photos; we ship weights, not photos |
| 3 | BGU campus | calibrates thresholds, fine-tunes, and is the only source we may quote numbers from |

## Do not

- Scrape the Instagram/Facebook archives. Meta's terms prohibit it and it is
  awkward to explain in an interview. Contact the community admins instead. (§4.3)
- Scrape any site whose terms forbid it. The Kaggle "Cat Re-Identification Image
  Dataset" is scraped from neko-jirushi.com with unclear licensing — a cautionary
  example, not a source.
- Commit cat photos, datasets, exports, model weights, or `.tfvars` — see `.gitignore`.
- Push to `main` or apply `infra/main` from a session, or call AWS with write
  intent unless the owner asked for that job. See "Workflow".

## Stack

**Collection:** Python 3.12 (Pillow, imagehash; httpx with h2 and PyJWT in
the events Lambda alone, for Apple's push) · Terraform · Lambda, no VPC ·
API Gateway HTTP API · S3 + DynamoDB on-demand · secrets in SSM Parameter Store
(SecureString).

**Delivery:** GitHub Actions. CI assumes a plan-only OIDC role on every PR;
deploys assume a separate OIDC role that only jobs in the `production`
environment can get. No long-lived AWS keys anywhere (`infra/README.md`).

**Research:** Python 3.12 · PyTorch · timm · wildlife-datasets · kornia. Local
only; no AWS.

**iPhone app:** SwiftUI (`native/swift/`), iOS 26 only, the system's own
controls; built and signed on GitHub's macOS runners. No Mac, no stored
certificate. Beside it until it is removed: Capacitor 8 around `web/`
(`native/`).

**In the browser:** MegaDescriptor-T-224, int8 ONNX, on ONNX Runtime Web 1.17.3
(WebAssembly, one thread; in the member app, inside the runtime's worker) —
self-hosted under the admin site's `model/`.
