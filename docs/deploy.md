# Deploying

`main` is what **staging** runs. **Production** runs the commit of the
latest `v*` tag. Every change reaches AWS the same way:

```
short-lived branch → pull request → CI (ruff, pytest, terraform plan)
  → the owner reads the plan and merges → push to main
  → deploy.yml, environment "staging": plan → apply → the commit gets "deployed/staging"
  → the owner tries it on staging, then tags that commit v…
  → deploy.yml, environment "production": the same steps, the same commit
```

Until 2026-11-10 a merge deployed production directly. Staging is a copy of
the app in an account of its own (`586943192664`): no Telegram bot, its own
Google client, never real contributor photos.

Nobody runs `make tf-apply` by hand any more, and no machine holds an AWS
access key. The roles, and why there are three of them: `infra/README.md`.
The owner's one-time setup: `docs/MANUAL_STEPS.md`.

## What the deploy job does

`deploy.yml` is one job with two destinations, chosen by what was pushed:
a push to `main` deploys staging, a `v*` tag deploys production. The steps
are the same, so production is deployed exactly the way staging was. One
run per environment at a time, and a run that has started is never
cancelled: a half-finished apply is worse than a late one.

0. For production only, **"Promote only what staging runs"**: the tagged
   commit must be on `main` and carry a green `deployed/staging` mark. A
   tag on anything else fails here, before any AWS credentials exist.
1. `make lint && make test`: the same checks as CI, again on the merged code.
2. `make build`: the Lambda zips.
3. `terraform plan -out=tfplan` on `infra/main`. It needs no secrets: the
   bot's and Google's live in AWS only, outside Terraform ("Secrets" below).
4. `terraform apply tfplan`: exactly the plan above, nothing recomputed.
5. If the plan changed any `aws_s3_object.site[...]`: `make site-invalidate`.
   The landing page is cached for up to a day; the admin app is not cached,
   so it never needs this.
6. **The front door answers,** checked from outside with no credentials:
   the app's page and `config.json` answer 200, and `/api/me` answers 401
   (API Gateway refusing a caller who is not signed in).
7. **Staging only, the smoke test** (`scripts/smoke_staging.py`): one
   made-up photo goes through the deployed pipeline (the record, the
   upload, the process Lambda, the queue, a fetched thumbnail), a
   collaborator is refused the queue, and the photo is deleted again. It
   runs under a role that can invoke the admin Lambda and nothing else,
   and that exists in the staging account alone. Its six lines are in the
   run's summary.
8. The commit gets the status `deployed/staging` or `deployed/production`,
   a green mark next to it on GitHub that links to the run. On staging it
   means applied **and** the smoke test passed: a commit whose smoke test
   failed cannot be promoted.

By hand (*Actions → Deploy → Run workflow*), with `plan_only` ticked, it
stops after step 3: run it from `main` to see what staging would get, or
from a `v*` tag to see what production would.

What decides which run may touch which account is not this file:

- each account's deploy role trusts only jobs in the GitHub environment of
  its own name (`infra/bootstrap`);
- GitHub lets only `main` claim `staging` and only `v*` tags claim
  `production` (*Settings → Environments*);
- a tag ruleset lets only the owner create `v*` tags.

## Promoting to production

1. On GitHub, open the commit list of `main`. The commit to promote has a
   green check whose details include **deployed/staging**.
2. Try it on the staging app.
3. *Releases → Draft a new release → Choose a tag*: type a new tag
   (`v2026.11.10`, or `v2026.11.10.2` for a second one that day), target
   that commit (or `main` if it is the latest), *Publish release*. From a
   terminal: `git tag v2026.11.10 <commit> && git push origin v2026.11.10`.
4. *Actions → Deploy*: the run for the tag shows its plan in the summary
   and applies it. Then the post-deploy checks below, on production.

The production plan holds everything merged since the last promote, not
one PR. Read it in the run's summary; the stop list in "Reading the plan"
applies to it just the same.

## Reading the plan

CI plans both accounts on every PR and posts one comment, updated on each
push, with two parts (since 2026-11-10; before that it planned production
only, which after the move to promote-by-tag was no longer what a merge
deploys):

- **Staging: what merging this deploys.** Read it before merging. It and
  the staging deploy's plan should match.
- **Production: what the next promote would deploy.** This change and
  every merged change not promoted yet, so it grows between promotes. It
  and the plan of the next tag's deploy should match.

Each part has the `Plan:` line and every resource that changes, destroys
first. The full plans are in the CI run (job `terraform`) and again in the
deploy runs. Each plan is followed by the plan check (`scripts/check_plan.py`).
The same two plans by hand, read-only: `make build`, then
`AWS_PROFILE=bgucats-staging-ro scripts/ci_plan.sh staging` (or
`bgucats-prod-ro` and `production`).

The comment carries actions and addresses only, never values, and says which
commit it describes. If it is missing or names an older commit, read the log
instead: posting it may fail without failing the check.

CI plans without taking the state lock, so it never blocks a deploy. Only
Deploy locks, and it runs one at a time. A CI plan that runs during an apply
can show changes the apply is making. Push again or re-run it if the comment
looks wrong after a merge. On 2026-11-02, with the lock, CI on `main` and on a
Dependabot PR failed with `Error acquiring the state lock` while Deploy ran.

**Stop, and do not merge, if the plan shows:**

- anything to **destroy** or **replace** (`-/+`, `must be replaced`). The
  deploy role cannot delete the data table, the buckets or the user pool
  anyway, so such an apply fails halfway. For the table and the media
  bucket the plan itself fails first (`Instance cannot be destroyed`:
  `prevent_destroy`).
- a change that turns off `deletion_protection_enabled` or
  `point_in_time_recovery` on the table, or a lifecycle rule on the media
  bucket that expires anything. Those are the ways a deploy could still
  lose data, and the guards above do not catch them.
- any `aws_ssm_parameter` or `aws_cognito_identity_provider` being
  created. Secrets are outside Terraform since 2026-10-31; one coming back
  would put its value into the state again.
- anything under `model/` in the admin web bucket (Terraform never owns it).

**Normal:**

- `aws_lambda_function.*` updated in place when its source changed, and
  only then: `make build` is reproducible, so the same source gives the
  same zip. The admin API and the Cognito trigger share one zip, so they
  change together. A new pip
  release or dependency version can change every zip once.
- `aws_s3_object.web[...]` / `aws_s3_object.site[...]` for the files the PR
  touched.

## Post-deploy checks

The deploy job checks the front door and, on staging, runs the smoke test
(steps 6 and 7 above). A red Deploy run with the apply green means one of
those failed: the run's log says which line. What no script checks is the
app in a person's hand:

On a phone with the installed app, signed in as an admin, unless a step
says otherwise. On staging, skip step 2 (there is no bot); its cats are
the made-up ones of `make seed-staging`:

1. The Actions run is green, and the apply summary has the same numbers as
   the plan.
2. **Telegram:** send the bot a photo. It answers "Got it!", and the photo
   shows up in the Queue within a minute (process Lambda).
3. **Queue:** the model strip ends at "knows N cats from M photos". Label
   one session. The toast says what the model had guessed.
4. **Capture, as a collaborator:** start an encounter, take a photo of a
   known cat, Done. "Who did you meet?" shows three cats within a few
   seconds. Answer it.
5. **Stats:** "Uploads that never arrived" reads 0. Stats → Recognition
   model shows the session from step 3.
6. **Landing page**, if it changed: the public URL shows the new version
   (`terraform -chdir=infra/main output site_url`).

If a model or photo fetch fails, check the media bucket's CORS rule first
(`s3.tf`).

## Rollback

```bash
git revert -m 1 <merge-commit>     # on a branch, then a PR like any other
```

Merge the PR, staging gets the previous state, and a new tag promotes it.
**Faster, when production is broken and staging's history is fine:** tag
the last good commit again under a new name (`v2026.11.10.rollback`). It
is on `main` and has its `deployed/staging` mark, so the promote check
passes and production goes back to it without waiting for a revert. `main`
still needs the revert before the next promote. What neither undoes:

- **Data.** Items and photos written by the newer code stay. Every change so
  far has been additive (new item types, new GSI2 entries), so the older
  code ignores them. Say in the PR if a change is not.
- **The model** under `model/` in the admin web bucket, which Terraform does
  not own. The older app simply doesn't load it.
- **Browser state.** IndexedDB stores stay at the version the newer app
  opened. Say in the PR if a change bumps a store and the old code cannot
  read it.

## When an alert email arrives

Each account emails the bootstrap admin when the app breaks
(`infra/main/alarms.tf`, since 2026-11-10). The subject starts with
`ALARM:` and names the alarm; an `OK:` email follows when five minutes
pass without another failure.

| Alarm | Means | Look at |
|---|---|---|
| `bgucats-process-errors` | a photo was stored but not processed: no thumbnail, not in the queue | log group `/aws/lambda/bgucats-process`; Stats → Bot health lists photos still pending |
| `bgucats-admin-errors`, `bgucats-admin-presignup-errors` | a request from the app, or a sign-in, got a 500 | `/aws/lambda/bgucats-admin`, `/aws/lambda/bgucats-admin-presignup` |
| `bgucats-ingest-errors` (production only) | a Telegram photo was not taken in; the sender was not told | `/aws/lambda/bgucats-ingest` |
| `bgucats-beacon-errors` | a landing-page visit was not counted; nobody noticed | `/aws/lambda/bgucats-beacon` |
| `bgucats-api-5xx` | the API answered 5xx, whatever the cause, including a Lambda that could not be invoked | the Lambda alarms above; then API Gateway's metrics |

Reading a log without the console:

```bash
aws logs tail /aws/lambda/bgucats-process --since 30m --profile bgucats-prod-ro
```

If it started right after a promote, roll back first ("Rollback" above)
and read the log afterwards.

**The first deploy into an account sends a confirmation email** ("AWS
Notification - Subscription Confirmation"). Nothing is delivered until its
link is clicked, once per account. Staging's alarms say `staging` in their
description; the subject only names the account's topic.

Not alarmed on purpose: 4xx answers, throttles and slow answers. Each
account's first ten alarms and thousand emails a month are free.

## When a red "plan check" stops a pull request

`terraform` in CI runs `scripts/check_plan.py` on the plan. It fails when
the plan holds a kind of resource that is not in
`infra/main/allowed-resource-types.txt`, a DynamoDB table that is not
`PAY_PER_REQUEST`, or a Lambda over 2048 MB or 120 s. Each is a cost
decision, not a mistake to patch around:

1. Decide whether the project should have it at all.
2. If yes: the deploy role must be allowed to create it (`infra/bootstrap`,
   applied before the PR can deploy), and a service the project has never
   used must be added to the organization's allowlist (`infra/org/scp.tf`,
   applied from the management account). Then the line in the allowlist
   file, in the same PR as the resource.

The check is the readable warning. What stops the deploy itself is AWS: the
deploy role's policy, and the service control policy.

## When a budget action fires

Each member account has a budget in the management account
(`infra/org/budgets.tf`). When the month's spending in an account crosses a
line, AWS Budgets emails the management account's address and attaches a
service control policy to that account:

| Spent | Policy attached | What it means |
|---|---|---|
| $20 | `bgucats-budget-freeze` | Nobody can create or change anything: not a deploy, not an administrator. The app keeps running; read-only sign-in and CI's plan still work. |
| $40 | `bgucats-budget-stop` | The app's own roles are denied too: the API answers with errors and uploads fail. The table, the photos and the static pages stay. |

Budgets sees spending some hours late, so the real figure is "the line,
plus what was spent before it noticed". AWS detaches both policies when the
next month starts.

**First find what is spending**, with the read-only profile, which still
works (`aws ce get-cost-and-usage`, or Billing → Cost Explorer in the
management account, grouped by service and by linked account).

**To fix it, the policy has to come off first**: while it is attached, an
administrator cannot change anything in that account either. From the
management account:

```bash
ACCOUNT=395591097129          # or 586943192664 for staging
aws organizations list-policies-for-target --target-id "$ACCOUNT" \
  --filter SERVICE_CONTROL_POLICY --profile mgmt-ro --query 'Policies[].[Id,Name]' --output text
aws organizations detach-policy --policy-id <p-... of the budget policy> \
  --target-id "$ACCOUNT" --profile mgmt-admin
```

It takes effect within a minute. The action will not attach it again this
month, so fix the cause before anything else. `FullAWSAccess` and
`bgucats-service-allowlist` (once it is on the root it will not be listed
here) are not budget policies: leave them.

## The iPhone app

The iPhone app is `web/` packed with Capacitor (`native/`), built on
GitHub's macOS runners and delivered through TestFlight. Nobody needs a
Mac. It is **not** part of a deploy: a merge still reaches staging's PWA at
once, and reaches the iPhone app only with the next build.

```
web/ ──scripts/native_bundle.py──> native/www ──npx cap sync ios──> the Xcode project
     (+ staging's config.json,                                   (native/ios, committed)
        + apiBase)
  → xcodebuild on a macOS runner → App Store Connect → TestFlight → the phone
```

**The builds talk to staging** (`SITE` in `.github/workflows/ios.yml`).
The app carries that deployment's public `config.json` and the address of
its API; nothing secret is packed into it.

`ios.yml` has two jobs:

| Job | Runs | Needs | Does |
|---|---|---|---|
| `simulator` | on a pull request that changes `native/`, the bundle script or the workflow; and before every upload | nothing | builds the app unsigned, starts it in an iPhone simulator, fails if it crashes, if the page does not load or if it throws an error. Keeps a screenshot and the app's log: the run's page → *Artifacts* → `ios-simulator` |
| `testflight` | only when started by hand, from `main` | the `testflight` environment | archives, signs and uploads. The build number is the run's number |

**To put a build on the phone:** GitHub → *Actions* → *iOS* → *Run
workflow* → branch `main`. About ten minutes later the run is green; Apple
then processes the build for some minutes more, and TestFlight on the phone
offers it. The owner starts it; Claude never does.

**Cost.** A macOS runner is $0.062 a minute against $0.006 for Linux
(2026-11), taken from the $18 of Actions usage GitHub Team includes each
month. Measured on 2026-11-11: a pull request's check is one job of under
three minutes, about $0.20; an upload is that job and a second one of
under two minutes, about $0.30 together. That is why nothing here runs on
every merge, and why a change to a screen is checked in the PWA and in
`tests/web` (which opens the packed app too, `test_native.py`), not by
building.

**Signing.** No certificate or profile is stored anywhere. The job hands
Xcode an App Store Connect API key (three secrets of the `testflight`
environment, typed by the owner) and Xcode signs with a distribution
certificate that Apple keeps. The environment's branch rule admits `main`
only, so a pull request's code can never read the key. The Team ID is the
environment's variable `APPLE_TEAM_ID`. The owner's one-time setup:
`docs/MANUAL_STEPS.md`, step 15.

**When the upload fails.** If the job stops at its first step, the
`testflight` environment lacks a value, and the error names it as GitHub's
settings do. The Team ID is a *variable*, `APPLE_TEAM_ID`; a secret of
that name, or of any other, is not read. Past that step, the job prints
Xcode's own account of a failure (the step "why the export failed"). The
usual causes: the API key's role is not Admin (Xcode cannot create the
certificate), the app record or the bundle ID `org.arip.bgucats` does not
exist in App Store Connect, or the build number was used before.

The first upload, build 3, went through on 2026-11-11: an unsigned
archive, signed at export with the certificate Apple keeps.

**Signing in, in the app.** Google refuses to sign anyone in inside an
app's web view, so the app opens iOS's own sign-in sheet
(`native/plugins/web-auth`, `ASWebAuthenticationSession`). iOS asks first
whether "BGU Cats" may use "amazoncognito.com" to sign in. Cognito answers
at `org.arip.bgucats://signin`, which the sheet hands back to the page,
and the page trades the code for tokens as the browser does. Three
settings in `infra/main` exist only for the app, and **a build signs in
only against a deployment that has them**, so the Terraform is merged and
deployed before the build that needs it:

| Where | What | Why |
|---|---|---|
| `cognito.tf` | `org.arip.bgucats://signin` on the client's callback list | Cognito refuses a sign-in that asks to be answered anywhere else |
| `api.tf` | a CORS configuration on the API, any origin | inside the app the pages' address is `capacitor://localhost`, so the API is another origin to them. API Gateway accepts only `http(s)` origins or `*`. No route takes a cookie; every call still needs its token |
| `admin_api.tf` | an `OPTIONS /api/{proxy+}` route without the authorizer | the web view asks first (a preflight, with no token), and on the authorized `ANY` route the answer was 401: every call failed with "Load failed". API Gateway answers this route from the CORS configuration; the Lambda never runs |
| `s3.tf` | `capacitor://localhost` beside the web address in the media bucket's CORS | uploads go from the page straight to the bucket |

The account that signs in must be on that deployment's allowlist, and for
staging also among its Google project's *Test users*
(`docs/MANUAL_STEPS.md`, 12d). The app is built against staging, whose
allowlist is its own: an admin of production is refused there ("This
Google account is not an admin or collaborator of BGU cats") until added
on staging, in the staging app's People screen or with
`make admin-add EMAIL=... PROFILE=bgucats-staging-admin`.

To check a deployment answers the app's preflight (an empty 204 with the
`access-control-*` headers; a 401 means every call from the app fails):

```bash
curl -si -X OPTIONS https://d2rysfyl47qmmz.cloudfront.net/api/cats -H "Origin: capacitor://localhost" -H "Access-Control-Request-Method: GET" -H "Access-Control-Request-Headers: authorization" | head -1
```

**What the builds cannot do yet** (`docs/ROADMAP.md`, 2e): the cat
guesses (the model's files are fetched from `/model/`, which inside the
app is not the server), and uploads with the app closed.

**Changing the shell.** `native/ios` is Capacitor's generated project with
a few edits (`native/README.md`). The Xcode project is edited as text and
proven by the `simulator` job on the pull request.

## Actions and Dependabot

Every action in `ci.yml`, `deploy.yml` and `ios.yml` is pinned to a full commit SHA, with
the version in a comment: a tag can be moved, a commit cannot, and `deploy.yml`
holds the deploy role. Nobody edits the SHAs by hand. Dependabot
(`.github/dependabot.yml`) opens grouped PRs once a month: one for actions, one
for the packages the Lambdas run on, one for dev tools. Each updates the SHA or
the pin for you.

Treat those PRs like any other, because merging one deploys:

- **Actions:** the PR's CI runs `checkout`, `setup-python`, `setup-terraform`
  and `configure-aws-credentials` with the new versions, under the CI role.
  The deploy role itself is first used by the merge. If that run fails, it
  fails before the apply, and a revert fixes it.
- **Runtime:** a new version of a package in `src/*/requirements.txt` changes
  that Lambda's zip, so the plan shows it updated in place. That is expected.
- **Dev tools:** a new `ruff` can flag existing code. That is a code change to
  make on the Dependabot branch or in its own PR first, not a reason to skip
  the check.

Left to a person on purpose, and the reasons are in the config file: major
versions of Python packages, `numpy` and `pandas`, and all of `research/`.

## The three things the pipeline does not do

All need an IAM Identity Center admin session
(`aws sso login --profile bgucats-prod-admin`, see `docs/codespaces.md`).
The owner runs them, or asks Claude to in a session the owner has signed
in to, except a secret's value, which only the owner types. A fourth lives
outside both app accounts: `infra/org`, the organization's guardrails
(`infra/README.md`; `docs/MANUAL_STEPS.md`, step 13).

**Publishing the recognition model.** The export needs torch, which has no
place in CI, and a new model is rare. The export needs the research
environment, never the root one:

```bash
python -m venv ~/.venvs/research && . ~/.venvs/research/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
pip install timm==1.0.30 onnx==1.23.2 onnxruntime==1.31.1 onnxscript==0.7.2 Pillow numpy
make model-export
deactivate
make model-publish PROFILE=bgucats-prod-admin
```

It prints the manifest and "a device downloads about 39.7 MB". Publish the
model before merging the code that loads it: nothing reads `model/` until
then, and the manifest is written last.

**`infra/bootstrap`** (the state backend and the GitHub roles). It cannot be
deployed by the role it creates. `infra/README.md` has the commands.

**Secrets.** The bot token, the webhook secret, the submitter salt (SSM
Parameter Store) and the Google OAuth client (Cognito's Google provider)
are set in AWS by `infra/scripts/set-secret.sh`, never by Terraform.
Anything Terraform manages is copied into its state, and the CI role reads
the state to plan, so any PR's workflow could read it. Until 2026-10-31
they came from `production` environment secrets; those GitHub secrets are
no longer used.

```bash
aws sso login --profile bgucats-prod-admin --use-device-code
AWS_PROFILE=bgucats-prod-admin infra/scripts/set-secret.sh telegram-bot-token
aws sso logout
```

The names: `telegram-bot-token` (paste from @BotFather after `/revoke`),
`telegram-webhook-secret` (generated), `google-oauth` (paste the client ID
and secret), `submitter-hash-salt` (new accounts only: it never replaces an
existing salt, because that would give every Telegram contributor a new
identity). The Telegram ones register the webhook themselves, at the API's
address, and stop if Telegram refuses it. **Revoking a token also drops the
bot's webhook**: on 2026-10-31 the first version of the script asked
Telegram for the old address, found none, and the bot went silent until
the webhook was set by hand. The ingest Lambda re-reads its secrets every 5
minutes, so a Telegram rotation can fail a few webhook calls for up to 5
minutes; Telegram retries them. Do it when the bot is quiet, and send the
bot `/start` afterwards.

In a **new account**, run `google-oauth` after the first deploy has created
the user pool and failed at the app client (which names the Google
provider), then deploy again; and `submitter-hash-salt` and both Telegram
ones (the second one registers the webhook).

## History

Notes from the hand-run deploys of 2026-10-29, kept for what they explain
about the code. Their `make tf-apply` and `git checkout` steps are
historical: today the same change would be a PR.

### Follow-up: uploads that never arrived (2026-10-29)

A small change on the same branch, deployed with the same commands
(`make lint && make test`, `make tf-plan`, `make tf-apply`). No model
publish, no new resources.

**Why.** On 2026-08-24, Telegram's `getFile` stalled past the 8-second
timeout five times in a row. urllib raised a bare `TimeoutError`, not a
`URLError`, so the handler fell through to its catch-all and acknowledged
each update. Five photos were lost: each record stayed `pending` (the write
order did its job), but nothing ever looked at `pending` records, and the
sender never heard about it. The logs (`/aws/lambda/bgucats-ingest`,
20:03–20:06 UTC) show it, and nothing like it has happened since.

**What changes:**

- **Ingest (Telegram and WhatsApp):** a timed-out or failed fetch now
  counts as a failed download (`OSError`, which covers both), and the bot
  replies "… Could you send it again?". Neither platform redelivers an
  update we acknowledge, so the person has to be the retry.
- **Pending records are on the status index** (`GSI2PK = STATUS#pending`)
  from the moment they are written, in the bots and in the app's
  `POST /api/encounters/{id}/media`. The flip to `unlabeled` already
  overwrote GSI2PK, so nothing else changes.
- **Stats → Bot health** gains "Uploads that never arrived": records still
  `pending` an hour after they were written, oldest first, with channel and
  photo ID (`stalled` in `GET /api/insights`).
- **The process Lambda skips an object with no photo record.** One was
  copied into `raw/` by hand on 2026-08-28 and processing it invented a
  half-built `PHOTO#01TESTVIDEODIAGNOSTICTEST1` record.

**Expected plan:** code updates to `aws_lambda_function.ingest`,
`.whatsapp`, `.process`, `.admin` and `.admin_presignup`, and
`aws_s3_object.web["app.js"]`. Nothing to create, destroy or replace.

**After apply:** open Stats. "Uploads that never arrived" reads 0. The five
old records predate the index, so they don't show up there (see "Old
records" below). Send the Telegram bot a photo: it should still say
"Got it!".

**Old records, cleaned by hand.** These are leftovers, not bugs. Back each
item up (`aws dynamodb get-item … > backup.json`) before deleting it:

- `PHOTO#01TESTVIDEODIAGNOSTICTEST1` and the `SHA#afda0768…` item that
  claims its hash — the diagnostic upload above.
- The five stuck photos, `PHOTO#01M0TNX24R01TCZR86BMS483XY`,
  `01M0TNXSJ40FHA8SPQPASZM19T`, `01M0TNYC1CXCX3MNYQ5A4A25QX`,
  `01M0TP1SK1J6NN3CDEJ78ET1NH`, `01M0TP26TX0FFG7Z51NAVJ9RHQ`. No S3 object
  exists for any of them, and the Telegram file IDs were never stored, so
  they cannot be recovered. Either delete them (and mark their four sessions
  the way Reject does: `rejectedAt`, `photoCount = 0`), or set
  `GSI2PK = STATUS#pending, GSI2SK = createdAt` on them so Stats lists them.
  Leave their `TGMSG#` items in place, as Reject does.

Sessions with no photos are **not** leftovers. Most were left empty on
purpose by Reject (they carry `rejectedAt`). The rest are encounters that
were opened and closed without a photo, and one is still a bot's
`LAST_SESSION` pointer. Keep them.

**Rollback:** check out the previous commit and run `make tf-apply`. The
`STATUS#pending` index entries are harmless to the old code. Its
`GET /api/stats` already counted `STATUS#pending` and simply always got 0.

The follow-up above was deployed on 2026-10-29, together with the fix below.


### Fix: Capture uploads stalled, and the model could not write (2026-10-29)

Deployed on 2026-10-29 (`make lint && make test`, plan, apply). The plan was
11 in-place updates: the admin role's policy, every Lambda's code (only
admin and the follow-up above really changed; the rest is zip noise), and
`app.js`, `capture.js`, `outbox.js`, `recognition.js`. No CloudFront
invalidation: the admin site is not cached.

**What went wrong.** An admin took 48 photos in Capture, and an hour later
they still said "uploading…". The API had received the encounters but not
one `POST /media`, and returned no 4xx or 5xx for them (API Gateway
metrics). So the outbox stalled on the phone, before its first call for a
photo. It re-saved every item, bytes included, to mark it "uploading". That
write, or any request that hung, stopped the whole pass. Nothing timed out,
and the screen gave no reason. Safari is known to refuse to store a Blob it
has just read out of IndexedDB, so that is the likely trigger. We could not
confirm it without the phone.

Separately, `POST /recognition/vectors` returned 500 (`AccessDenied` on
`dynamodb:BatchWriteItem`), so no vectors were ever shared and Capture's
guesses were always hidden. Blind queue guesses would have failed the same
way, on `dynamodb:ConditionCheckItem` (a transaction's ConditionCheck step
is authorized on its own). None had been tried yet: the queue was empty,
and an empty queue never started the model.

**What changed:**

- **Outbox (web/outbox.js):** a photo's bytes are written once and never
  again. Its state goes in a new `states` store (IndexedDB v2); items saved
  by v1 are read as they are. Every API call times out after 35 s and an S3
  upload after 180 s. A failure that belongs to one photo (a 5xx, a refused
  upload) no longer blocks the photos behind it. An S3 4xx marks the photo
  failed, with "Try again". Capture shows the last error ("Retrying — last
  try: …").
- **Encounters are created on the server with their first photo.** One that
  is opened and closed empty never reaches the API. `GET /api/encounters`
  leaves out encounters with no files.
- **IAM:** the admin role gets `BatchWriteItem` and `ConditionCheckItem`.
- **The Queue runs the model even when empty**, so an admin's visit always
  learns and shares the cats. Capture says "The app doesn't know any cats
  yet" instead of hiding the panel. An admin's own learned gallery is no
  longer replaced by the shared copy.
- **Caching:** presigned photo URLs carry
  `response-cache-control=private, max-age=86400, immutable`. The app reuses
  the first URL it saw for each object until five minutes before it
  expires, and keeps that across launches (localStorage `bgucats.photoUrls`).
  A screen's GETs are reused for 15 s. After that, the screen shows the last
  answer at once and redraws only if a refresh changed something. Any action
  the person takes clears that memory.

**Verified, headless (real app, stub API answered by the live Lambda's
GETs):**
- An old v1 outbox seeded with 48 stuck photos uploaded 47 of them within 4
  s of the new app loading. The one seeded as failed waited for "Try again".
- The empty queue learned 20 cats from 228 photos and shared 10 vector
  batches. Capture then asked "Is it one of these?" and recorded the pick.
- After the first visit, switching between screens took 0.02–0.06 s and
  downloaded no photos.

**Rollback:** check out the previous commit and run `make tf-apply`. An
IndexedDB opened at v2 still works with the v1 code: v1 opens without a
version, ignores the `states` store, and reads every item as queued.


### The model's guess in plain sight, and guesses that never recorded (2026-10-29)

**Asked for:** the admin wanted the model's guesses easy to see. Until now
the guess showed only after labeling, as a toast that disappeared within
seconds. The admin decided that seeing it first does not sway their
judgment.

**What changes:**

- **Queue cards** show "Model's guess" between the header and the photos:
  the top three, each with its cover, rank and cosine similarity. #1 is
  emphasised. It redraws as the model reaches the session ("getting ready…",
  "looking at these photos…"). Tapping a guess opens the picker.
- **The picker** shows the same three above the full list. One tap labels,
  like any tile.
- After a label, the verdict toast ("The model's first guess was … ✓")
  stays for 9 s instead of 3.5 s.
- **Fix:** `POST /api/sessions/{id}/prediction` refused every real session
  with 409 "already labeled". Bots and the app write sessions with
  `catId = null`, a null attribute *exists*, and the transaction's check was
  `attribute_not_exists(catId)`. It is now `attribute_not_exists(catId) OR
  attribute_type(catId, :null)`. The test fixture had left `catId` out, which
  is why the tests never caught it. A new test writes it as null. In
  production, 0 predictions had been recorded, and the five app sessions
  labeled at 13:10–13:13 were each refused once (API Gateway 4xx).

**What this means for the numbers:** the model's live record stays honest,
because each guess is still recorded before the label exists. Labels made
from now on, though, may lean on the guess. Lookalikes are where that would
show. Keep this in mind before using these labels to calibrate thresholds or
to fine-tune.

**Verified, headless (live Lambda GETs, a stub queue of three real
sessions, phone and desktop widths):** each card shows three guesses and
the picker matches them. The prediction POST happens before the assign, and
one tap in the picker labels. Then the toast reads "The model's first guess
was … too ✓".

**Expected plan:** code updates to `aws_lambda_function.admin` and
`.admin_presignup` (plus zip noise on the others), and
`aws_s3_object.web["app.js"]`, `["recognition.js"]`, `["styles.css"]`.


### "Who did you meet?" after each encounter, and uploads that keep going (2026-10-29)

**Asked for:** collaborators should see the model's guess for every
encounter and say which cat it was. The design should be good enough for
the early version of the real app. Uploads must not slow down, and should
keep going when the phone is locked or the app is closed, if a PWA can do
that.

**What changes:**

- **Capture's result screen.** "Done" opens "Who did you meet?" instead of
  closing the encounter. It shows the photos with their upload state and
  asks "Is it one of these?" over the model's three. The other choices are
  "Another cat…" (every cat, the model's order first, with a filter), "A cat
  that isn't here", "Not sure", "Take more photos" and "Skip". After an
  answer: "You said X · Encounter #N with this cat", whether the model
  agreed, then "Next cat" (straight into a new encounter) or "Finish".
  Admins get the same screen with similarity scores. The ranking is
  computed in the background while shooting and kept with the encounter, so
  a reload returns to the result screen.
- **Guesses are on by default.** The model downloads in the background from
  the first Capture visit. Only a data-saver phone is asked first.
- **Your recent encounters** shows "you: X ✓/✗" and "model: Y ✓/✗" against
  the label (`GET /api/encounters` adds `modelCatId` and `modelCatName` to
  `pick`).
- **Uploads:** three at a time. The screen is kept awake while files wait
  (Wake Lock). **Background Sync** (Chrome on Android): the outbox registers
  it with every photo and when the app is hidden, and sw.js uploads the
  queue with the app closed. The tokens are copied to IndexedDB
  `bgucats-auth` for it. Capture says which of these applies ("You can leave
  the app…" or "Keep the app open…").

**The iPhone limit, stated plainly:** Safari has no Background Sync or
background upload API, and suspends a hidden web app within seconds. On an
iPhone, uploads move only while the app is open on screen. The app keeps the
screen from locking while files wait, and tells the person to keep it open.
A native app would be the only way past this.

**Verified, headless (live Lambda GETs as a collaborator, stub writes):**
- 4 photos of one cat, then Done: "Is it one of these?" was up within a
  second, #1 was right, and the answer recorded "Encounter #7 · The model
  thought so too ✓".
- "Another cat…" listed all 22 cats, and the filter worked. A reload on the
  result screen came back to it with the guess.
- Offline, the guess still came (the model is cached).
- In full Chromium, 3 photos taken offline uploaded through the service
  worker 1 s after the signal came back, with no page open. Chrome's
  stripped-down headless shell never fires Background Sync, so a test there
  proves nothing.

**Expected plan:** code updates to `aws_lambda_function.admin`,
`.admin_presignup` (plus zip noise), and `aws_s3_object.web["app.js"]`,
`["capture.js"]`, `["outbox.js"]`, `["sw.js"]`, `["styles.css"]`,
`["recognition.js"]` if changed.

### Fix: a photo could be dropped right after its encounter was made (2026-11-10)

Found by seeding staging through the API (`scripts/seed_campus.py`), not by
a report.

- **What happened:** the phone sends an encounter and then, at once, its
  first photo's record. The second call looked the encounter up with
  DynamoDB's default read, which may answer from a copy that has not
  received a write made milliseconds earlier. It then answered 404 "no such
  encounter", and the outbox treats a 404 as final (`isPermanent` in
  `web/outbox.js`): the photo was given up, with a message on the phone
  and no trace in the table. The same could happen between a photo's
  record and its confirmation, and between a new cat and its first label.
  On staging: one encounter in twelve when the calls come back to back.
  How often it hit real phones is unknown, since nothing recorded it.
- **Fix:** every single-record read in the API (`_item` in
  `src/admin/handler.py`) and the two in the process Lambda are strongly
  consistent. The process Lambda's check had the quieter version of the
  same fault: an object whose record was "not there" is skipped for good.
- **Not changed:** lists (the queue, a cat's photos) come from indexes,
  which DynamoDB can only read eventually consistent. A photo may take a
  moment to appear in a list; nothing is decided on its absence.
- **Cost:** one read unit for such a read instead of half of one.
