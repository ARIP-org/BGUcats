# Manual steps: bgucats moves to its own account, deployed only by GitHub

Everything in the move that code cannot do. Written 2026-10-30, for the owner.
Do the steps **in order**. Each one says what breaks if it is skipped or done
out of order. The order is chosen so that the old account keeps running
production, untouched, until the new one has been proven, and so that no
step can lose the dataset.

| | |
|---|---|
| Old account | `851725214678`: production until step 8; now the organization's management account, running nothing since step 9 (2026-11-07) |
| New account | `395591097129` `sasha-bgucats-prod`: production after step 8 |
| Region | `us-east-1` |
| SSO profiles | `mgmt-ro`, `mgmt-admin` (old account), `bgucats-prod-ro`, `bgucats-prod-admin` (new) |
| Repo | `ARIP-org/BGUcats` (owner ID 353802310, repo ID 1339652949); `sasha720709/BGUcats` (owner ID 254865293) until 2026-11-07, step 11 |
| CI role | `arn:aws:iam::395591097129:role/bgucats-github-actions-ci` |
| Deploy role | `arn:aws:iam::395591097129:role/bgucats-github-actions-deploy` |
| Cognito domain | `bgucats-app` (old: `bgucats-admin`) |
| Old user pool | `us-east-1_iLd1I4gJ9` |
| Old IAM user | `sasha-bgucats-admin` (group `admins` → AdministratorAccess), keys ending `…F4MF` and `…IITS`: all deleted in step 9 |

**The pull requests:** PR #1 `consolidate-main` (main is production), PR #2
`deploy-oidc` (account-agnostic infra, the deploy role, `deploy.yml`, this
file), PR #3 `migrate-data` (`scripts/migrate_account.py`).

**Rules for every command below:**

- Run `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN` once
  per shell. Environment keys win over any `--profile` or `AWS_PROFILE`.
- Every command names its profile. The Makefile targets take `PROFILE=` and
  refuse to run against any account but `395591097129`
  (`infra/scripts/aws-guard.sh`).
- Secrets go from AWS straight into `gh`, never through the screen or a file.

**What protects the data during the move:** the old account is only ever
*read* until step 9, through `mgmt-ro` and through a read-only wrapper in
the migration script. The new account is only ever *added to*: the script
never replaces an object, never replaces a differing item unless told to
for one prefix, and never deletes. The old copy stays whole until the new
one has run for two weeks and a final `verify` says nothing is missing
(step 9).

---

## 1–2. Done: the organization, Identity Center and the new account

Check that all four profiles work and point where they should:

```bash
aws sso login --profile bgucats-prod-ro --use-device-code   # signs in all four: one SSO session
for p in mgmt-ro mgmt-admin bgucats-prod-ro bgucats-prod-admin; do
  printf '%-20s ' "$p"; aws sts get-caller-identity --profile "$p" --query Arn --output text
done
```

Expected: the `mgmt-*` lines show `851725214678:assumed-role/AWSReservedSSO_...`,
the `bgucats-prod-*` lines `395591097129:...`, ReadOnlyAccess for `-ro` and
AdministratorAccess for `-admin`. If `~/.aws/config` has a section
`[profile profile bgucats-prod-ro]` (a name typed as "profile …"), rename it
to `[profile bgucats-prod-ro]`.

---

## 3. Merge PR #1, then PR #3; tag the old heads; delete the stack

Both before the ruleset (step 5e). Neither can deploy: `main` has no deploy
workflow until PR #2. Their `terraform` check fails the same way `main`'s
has since 2026-10-29. That is expected; step 6 fixes it.

1. **PR #1** (`consolidate-main` → `main`): **Create a merge commit**, not a
   squash, so the tags below stay reachable from `main`.
2. Tag the old heads, check them, and push the tags:

```bash
cd /workspaces/BGUcats
git fetch origin && git checkout main && git pull --ff-only
git tag -a rollback/admin-labeling-tool 5ba09d1ff36f1237f7fe5306102eb5afc7425e1c -m "production until 2026-10-28"
git tag -a rollback/app-preprod         2f5317552babd4133e7d62d5fcae0c51584608e8 -m "production 2026-10-28 to 2026-10-29"
git tag -a rollback/recognition-labeling 0dc5dd8b9ba66a1ac7eef29262fa938bd83fe2fc -m "production from 2026-10-29, merged into main"
git tag -a rollback/research-hopeful-feynman f20cdef7f7c06d835b7e49e906cad4f6423ae19d -m "research track 1b, merged into recognition-labeling"
git tag -a rollback/main-before-consolidation e8db9bd354750e237c939d538f73226705112ca5 -m "main before PR 1"
for t in admin-labeling-tool app-preprod recognition-labeling research-hopeful-feynman main-before-consolidation; do
  git merge-base --is-ancestor "rollback/$t" origin/main && echo "ok $t" || echo "NOT IN MAIN: $t"
done
git push origin rollback/admin-labeling-tool rollback/app-preprod rollback/recognition-labeling \
  rollback/research-hopeful-feynman rollback/main-before-consolidation
```

   All five must print `ok`. Only then delete the stack:

```bash
git push origin --delete admin-labeling-tool app-preprod recognition-labeling claude/hopeful-feynman-l098o2
git branch -D admin-labeling-tool app-preprod recognition-labeling claude/hopeful-feynman-l098o2
```

3. Delete `consolidate-main` with the button on the merged PR. GitHub
   retargets PR #2 and PR #3 to `main`. If it does not: *Edit* next to the
   title → base `main`.
4. **PR #3** (`migrate-data`): merge commit. It adds a script and its tests,
   nothing else.

**If skipped:** PR #2 would deploy an older app the moment it applies.
**Deleting branches before the tags are pushed** loses the only names for
those production states.

---

## 4. PR #2: read it

Nothing to run. The account ID appears in one file,
`infra/main/backend/prod.hcl`, and in the docs.

---

## 5. GitHub and Google settings

**5a–5c must happen before step 6.** The deploy role trusts any job in the
environment `production`. GitHub creates an environment the first time a
workflow names it, with **no** protection. If the role exists while
`production` is unprotected, a workflow on any branch, including one pushed
by a Claude session, could assume it.

### 5a. Environment `production`

Repo → *Settings* → *Environments* → **New environment** → `production`:

1. *Deployment branches and tags* → **Selected branches and tags** → *Add
   deployment branch or tag rule* → Ref type *Branch* → `main`.
2. *Required reviewers* is not offered for a private repo on the free
   plan (the API refuses it), so there is none. What stands between a
   merge and an apply is the ruleset (5e), the plan in the PR, and
   `plan_only` until 6d.2.

Done on 2026-10-30, with the variables (5b) and the six secrets (5c).

### 5b. Variables (the role ARNs, not secrets)

```bash
env -u GITHUB_TOKEN gh auth login --hostname github.com --git-protocol https --web
alias ghx='env -u GITHUB_TOKEN gh'
R=ARIP-org/BGUcats          # sasha720709/BGUcats when this ran, 2026-10-30
ghx variable set AWS_CI_ROLE_ARN -R $R --body arn:aws:iam::395591097129:role/bgucats-github-actions-ci
ghx variable set AWS_DEPLOY_ROLE_ARN --env production -R $R --body arn:aws:iam::395591097129:role/bgucats-github-actions-deploy
ghx variable list -R $R; ghx variable list --env production -R $R
```

`AWS_CI_ROLE_ARN` is a repository variable because a PR run has no
environment. The codespace's own `GITHUB_TOKEN` cannot write variables or
secrets, hence the `ghx` login.

### 5c. Environment secrets, copied from the old account

These are infra/main's six variables. **The salt must be byte-identical to
the old one:** bot submitters are `sha256(salt + id)`, so a different salt
makes every existing contributor a new person. The values are read from the
old account with `mgmt-ro` and piped into `gh`, which never prints them:

```bash
p()   { aws ssm get-parameter --profile mgmt-ro --with-decryption --name "$1" --query Parameter.Value --output text | tr -d '\n'; }
idp() { aws cognito-idp describe-identity-provider --profile mgmt-ro --user-pool-id us-east-1_iLd1I4gJ9 \
          --provider-name Google --query "IdentityProvider.ProviderDetails.$1" --output text | tr -d '\n'; }

p /bgucats/telegram/bot-token      | ghx secret set TELEGRAM_BOT_TOKEN      --env production -R $R
p /bgucats/telegram/webhook-secret | ghx secret set TELEGRAM_WEBHOOK_SECRET --env production -R $R
p /bgucats/submitter-hash-salt     | ghx secret set SUBMITTER_HASH_SALT     --env production -R $R
idp client_id                      | ghx secret set GOOGLE_CLIENT_ID        --env production -R $R
idp client_secret                  | ghx secret set GOOGLE_CLIENT_SECRET    --env production -R $R
aws dynamodb query --profile mgmt-ro --table-name bgucats-data --index-name GSI2 \
  --key-condition-expression 'GSI2PK = :a' --filter-expression 'addedBy = :t' \
  --expression-attribute-values '{":a":{"S":"ENTITY#ADMIN"},":t":{"S":"terraform"}}' \
  --query 'Items[0].email.S' --output text | tr -d '\n' \
                                   | ghx secret set BOOTSTRAP_ADMIN_EMAIL   --env production -R $R
ghx secret list --env production -R $R     # six names, no values
```

If `p` fails with `AccessDenied` on KMS, use `--profile mgmt-admin` in it
instead. The `tr -d '\n'` matters: with a trailing newline it would be a
different salt. Step 7's `verify` compares every `/bgucats/*` value in both
accounts by digest, so a mistake here is caught before cutover.

The Telegram token and the webhook secret belong to the same bot, so the
bot keeps its name and contributors keep their chats. Only the webhook URL
moves (step 8).

### 5d. Google: the new redirect URI

[Google Cloud console](https://console.cloud.google.com/) → project
`bgucats` → *APIs & Services* → *Credentials* → the OAuth client → add
under **Authorized redirect URIs**, keeping the old one until step 9:

```
https://bgucats-app.auth.us-east-1.amazoncognito.com/oauth2/idpresponse
```

Check that it was **saved**: the list must show both URIs. On 2026-10-30
only the old one was there after the cutover, and the new app's sign-in
failed with `Error 400: redirect_uri_mismatch` until it was added. Google
can take a few minutes to pick up a change.

### 5e. Ruleset on `main`

After step 3: *Settings* → *Rules* → *Rulesets* → **New branch ruleset**:
name `main`, **Active**, bypass list **empty**, target **default branch**.
Rules: **Restrict deletions**, **Block force pushes**, **Require a pull
request** (0 approvals: GitHub never lets an author approve their own PR;
methods Merge and Squash), **Require status checks**: `python` and
`terraform`.

**If skipped:** without 5a, see above. Without 5b/5c, CI and Deploy fail
early with a message naming the missing variable or secret. Without 5d,
sign-in fails with `redirect_uri_mismatch`. Without 5e, anything with push
access can push to `main`, and that deploys.

---

## 6. Build the new account

### 6a. Two checks on a brand-new account

```bash
# The AWS-managed SSM key is created on first use. Both Terraform roots look
# it up at plan time, before anything has used it. Describing the alias
# creates it:
aws kms describe-key --key-id alias/aws/ssm --profile bgucats-prod-admin --query KeyMetadata.KeyId

# New accounts can start at 10 concurrent Lambda executions. Enough to run,
# but if it says 10, ask for 1000 in Service Quotas (Lambda → Concurrent
# executions) so the copy in step 7 is not throttled.
aws lambda get-account-settings --profile bgucats-prod-ro --query AccountLimit.ConcurrentExecutions
```

### 6b. Apply `infra/bootstrap`, from PR #2's branch

```bash
cd /workspaces/BGUcats
git fetch origin && git checkout deploy-oidc && git pull --ff-only
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
export AWS_PROFILE=bgucats-prod-admin
infra/scripts/aws-guard.sh                  # must say: account 395591097129
ls infra/bootstrap/terraform.tfstate 2>/dev/null && echo "STOP: a local state is here; move it away first"
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap plan -out=bootstrap.tfplan
```

**The plan must say `Plan: 17 to add, 0 to change, 0 to destroy.`**: the
state bucket and its versioning, encryption and public-access block, the
lock table, the OIDC provider, the CI role and its 3 policies, the
boundary, and the deploy role and its 5 policies. Anything to import,
change or destroy means the profile points at the wrong account, or an old
state file is present: stop.

```bash
terraform -chdir=infra/bootstrap apply bootstrap.tfplan
terraform -chdir=infra/bootstrap output
aws s3 cp infra/bootstrap/terraform.tfstate s3://bgucats-tfstate-395591097129/bootstrap/terraform.tfstate
rm infra/bootstrap/bootstrap.tfplan
unset AWS_PROFILE
```

The two role ARNs in the output must match step 5b's variables. Before
every later bootstrap plan, fetch the state back from that key
(`infra/README.md`).

### 6c. Merge PR #2, check the OIDC claims

1. On PR #2, **re-run the failed `terraform` check**. It plans against the
   new, empty account: everything in infra/main **to add**, nothing to
   change or destroy. Green.
2. Merge PR #2 (merge commit). The push starts **Deploy** in plan-only
   mode (`PLAN_ONLY_ON_PUSH: "true"`).
3. *Actions* → **OIDC claims (debug)** → *Run workflow* on `main`. The log
   shows something like
   `"sub": "repo:sasha720709@254865293/BGUcats@1339652949:environment:production"`.
   The deploy role accepts `repo:sasha720709@*/BGUcats@*:environment:production`.
   - **Matches:** go on.
   - **Differs:** put the printed `sub` in the `sub` condition of
     `infra/bootstrap/deploy_role.tf` (`*` only in place of the numeric
     IDs), re-run 6b from a branch with that change (one in-place update of
     the deploy role), and merge it as a PR. **Never** widen it to
     `...:*`: that matches every PR run.
   - Then delete `.github/workflows/oidc-claims-debug.yml` in a small PR.

   Done on 2026-10-30 without running it: Deploy assumed the role from
   `production` on its first two runs, which only a matching `sub` allows.
   The workflow is deleted.

### 6d. Plan only, then the first apply

1. *Actions* → **Deploy** → *Run workflow*, `plan_only` ticked. Expected:
   `Plan: N to add, 0 to change, 0 to destroy`. Among the adds: the table
   with `deletion_protection_enabled = true` and `point_in_time_recovery`,
   three buckets ending `-395591097129`, the user pool domain
   `bgucats-app`, and two CloudFront distributions. A plan of an empty
   account reads almost nothing, so a missing deploy permission shows up
   at apply, not here.
2. **Turn on applies:** a PR that flips both switches in `deploy.yml`:

   ```diff
   -        default: true
   +        default: false
   ...
   -  PLAN_ONLY_ON_PUSH: "true"
   +  PLAN_ONLY_ON_PUSH: "false"
   ```

   Merging it is the first real deploy. It builds the whole app in the new
   account in 10–20 minutes, most of it CloudFront.
3. **If the apply stops halfway**, nothing is lost: the new account holds no
   data yet, and the next run picks up from the state. Two likely causes:
   - `AccessDenied ... X`: the deploy role lacks an action that creating
     some resource needs. Add `X` to the right statement in
     `infra/bootstrap/deploy_role.tf` on a branch, apply bootstrap (6b,
     state fetched back first), merge, and re-run Deploy.
     **This happened on 2026-10-30:** 88 of 89 resources were created, and
     the API's `$default` stage stopped on `apigateway:TagResource`, which
     AWS checks when a resource is created with tags. Fixed by adding it
     (and `UntagResource`) to the role, applied with bootstrap.
   - CloudFront: *"Your account must be verified before you can add new
     CloudFront resources"*. This happens to some new accounts. Open a
     support case (*Account and billing*, free), then re-run.

   **Done on 2026-10-30:** after the fix above, the merge of #8 applied
   the last resource (`1 added`). The new account has the whole app.
4. **Plan only once more:** `No changes.` That proves the apply is
   complete and the builds are reproducible.
5. Note the new addresses (outputs are not secret):

```bash
make tf-init PROFILE=bgucats-prod-ro
AWS_PROFILE=bgucats-prod-ro terraform -chdir=infra/main output
```

**Do not open the new app yet,** and do not run `make model-publish`
against the new account: the model and the data come across in step 7,
byte for byte.

**From here until step 8, every merge to `main` deploys only to the new
account.** The old account keeps running the tree it has today, and nothing
changes it. Hold app changes until the move is done.

---

## 7. Copy the data (you run it, the script checks it)

`scripts/migrate_account.py` (PR #3). Every subcommand defaults to a dry
run, reads the old account through `mgmt-ro`, and writes the new one
through `bgucats-prod-admin`. It prints both account IDs first and stops
unless they are `851725214678` → `395591097129`. Run it from a checkout of
`main` with the dev requirements installed (`pip install -r requirements-dev.txt`).

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
alias migrate='python scripts/migrate_account.py'
```

### 7a. Before the freeze, any time after step 6

The bulk of the bytes, while production keeps running. **Media goes before
the table:** each object that lands in `raw/` starts the process Lambda,
which skips objects that have no photo record. If the record were already
there, it would re-process the photo and rewrite its derivatives and
`processedAt`. `migrate media` refuses to run once the table holds anything
but `ADMIN#` rows.

```bash
migrate media            # dry run: "would copy" per prefix, no writes
migrate media --apply    # raw/, derived/, exports/; safe to re-run
migrate model            # dry run
migrate model --apply    # model/ byte for byte, manifest.json last
migrate verify --only media
migrate verify --only model
migrate verify --only ssm
```

`verify --only ssm` must show **`same`** for the three `/bgucats/*`
parameters: the Telegram token, the webhook secret and the salt. (The old
account's `/bgucats/whatsapp/*` are ignored: the WhatsApp bot was removed.)
A `differ` means an environment secret from 5c differs from the old value:
set it again (5c), run Deploy, and check again. **Do not go on with a
differing salt.**

The copied model keeps its version hash, so every stored vector and
recorded guess stays valid. Re-publishing would keep them valid only if the
export came out bit-identical, and nothing would tell you if it did not.

### 7b. The freeze (an evening, about an hour)

Writes to the old account stop, the table is copied once, and the bot moves
over. Nothing is lost: Telegram holds undelivered updates for 24 hours.

**`scripts/cutover.sh` runs steps 2 and 4–6 below, and 8.1, in one go**,
after you have done 1 and 3 by hand:

```bash
cd /workspaces/BGUcats && git checkout main && git pull --ff-only
aws sso login --profile bgucats-prod-admin --use-device-code && bash scripts/cutover.sh; aws sso logout
```

Until Telegram has moved to the new account, any failure (or Ctrl-C)
points it back at the old one, so production is never left paused. The
steps below are what it does, and how to do them by hand.

1. **Tell the collaborators** a day ahead. At the start, everyone opens the
   old app until Capture shows nothing waiting to upload, then stops using
   it. A photo still queued in an old install would upload to the old
   account later: each install's queue lives in its own origin's storage,
   and the new app is a new origin.
2. **Write down the old webhook, then pause Telegram.** `deleteWebhook`
   *without* `drop_pending_updates`, so Telegram keeps new messages queued
   instead of delivering them:

   ```bash
   T=$(aws ssm get-parameter --profile mgmt-ro --with-decryption --name /bgucats/telegram/bot-token --query Parameter.Value --output text)
   curl -sS "https://api.telegram.org/bot$T/getWebhookInfo" | jq '{url, pending_update_count}'   # write the url down: the way back
   curl -sS "https://api.telegram.org/bot$T/deleteWebhook"; echo
   unset T
   ```

3. **The old WhatsApp bot** still runs in the old account until 9c, and
   the new account has none. If its Meta app still exists, delete it now
   (developers.facebook.com → the app → *App settings* → *Advanced* →
   *Delete app*), so that nothing lands in the old table after the copy.
4. **Last media copy:** `migrate media --apply` again. It copies only what
   arrived since 7a, while the table is still empty.
5. **The table:**

   ```bash
   migrate table                                    # dry run
   migrate table --apply --overwrite-prefix ADMIN#
   ```

   The dry run must show `would copy` for everything except one `would
   overwrite` under `ADMIN#`. That is the row Terraform wrote for
   `BOOTSTRAP_ADMIN_EMAIL`, which has no `role`. The old row has one
   (`collaborator` as of 2026-10-29), and the copy keeps it. Any other
   `conflict` means something wrote to the new table: stop and look.
   `RATE#` and `MGREPLY#` show as `skipped`.
6. **Prove it:** `migrate verify`. Expected: **`MATCH`**. Every prefix has
   source = dest, with 0 missing, 0 differ and 0 extra. The GSI2PK table
   shows the same number of cats, sessions per status, predictions, picks
   and vectors on both sides, and all three SSM parameters are `same`. If only
   a GSI lags ("catching up?"), wait a minute and run it again. For
   anything else, do not cut over: the old account is untouched, so resume
   Telegram there with the URL from step 2 (see "Way back" below) and find
   out why.

The copy stays faithful only while nothing else writes to the new table,
so nobody opens the new app before step 8.

---

## 8. Cutover

**Done on 2026-10-30**, in the afternoon rather than the evening, since
nobody was using the app. `scripts/cutover.sh` ran 12:28–12:31 UTC and the
copy verified as `MATCH`. Telegram and Capture work in the new account.
Step 9 was done on 2026-11-07.

1. **Telegram to the new account.** The queued messages arrive within
   seconds:

   ```bash
   make tf-init PROFILE=bgucats-prod-ro
   AWS_PROFILE=bgucats-prod-admin infra/scripts/set-telegram-webhook.sh
   ```

   The `getWebhookInfo` it prints shows the new `execute-api` URL,
   `pending_update_count` falling to 0, and no `last_error_message`.
2. **The app:** on each phone, open `admin_url` from step 6d.5, install it
   (Share → Add to Home Screen, or the install button), and sign in with
   Google. Keep the old app on the home screen until its queue is empty,
   then delete it.
3. **Smoke test** (`docs/deploy.md` → "Post-deploy checks"). A Telegram
   photo gets "Got it!" and shows up in the Queue within a minute. A Capture
   encounter as a collaborator shows three cats under "Who did you meet?".
   An admin labels one session. Stats → "Uploads that never arrived" reads
   0. Stats → Recognition model lists the copied predictions.
4. **The next day:** `migrate verify --only table`. Now `extra` and
   `differ` are expected (new work in the new account), but **`missing`
   must be 0**. Anything missing landed in the old account after the copy.
   Bring it over media first, then items, both create-only, so nothing in
   the new account is touched:
   `migrate media --apply --allow-nonempty-table`, then `migrate table --apply`.

   **Done on 2026-11-02, later than planned, and it found something.** One
   encounter (15 files: session `01M696VEWN451Q707YRB6XQSFM`, with its pick) had
   been shot in the **old app** on 2026-10-31, a day after the cutover. It was
   copied as above, and `missing` is now 0. An installed old app keeps working
   until step 9, so anything it uploads lands in the old account.

   `TRAFFIC#` items can show as `missing` again at any time and do not matter:
   the old landing page and its schedule keep counting until step 9. Before
   copying anything back, check when a missing ULID was made. One made before
   the cutover was deleted in the new account on purpose, and the copy would
   bring it back.

### Way back, until step 9

**Gone since step 9 (2026-11-07).** Kept for the record.

The old account is complete and still running. Point Telegram back at it
(`setWebhook` with the URL written down in 7b.2 and the same
`secret_token`), and use the old app. Work
done in the new account in the meantime can be copied back with the same
script, accounts reversed:
`--source-profile bgucats-prod-ro --source-account 395591097129 --dest-profile mgmt-admin --dest-account 851725214678`.

---

## 9. Decommission the old account

Planned for two weeks after the cutover. **The owner decided on 2026-11-02 not
to wait.** Do it in this order. `851725214678` is the organization's management
account, so the account itself stays: it holds the organization, Identity Center
and billing. Closing it would take production with it. What goes is everything
bgucats has inside it.

Two things here cannot be undone: 9c ends the old CloudFront addresses for good,
so the QR codes on printed posters stop working, and 9e deletes the old data.

**Done on 2026-11-07, all of it, 9e included.** Claude ran the commands in the
owner's SSO session, at the owner's request (`CLAUDE.md`, "Workflow"). What
happened, where it differs from the text below:

- **9a** passed: `missing` = 0 except two `TRAFFIC#` counters, salt `same`,
  production's point-in-time recovery `ENABLED` and deletion protection on.
- **9b:** backup `bgucats-data-before-decommission`, `AVAILABLE`. It is the only
  bgucats thing left in the account. Keep it.
- **9c:** the owner had already deleted every Lambda and both APIs in the console
  and disabled the three distributions. The destroy plan then had 66 resources
  instead of about 90, and applied with no errors.
- **9d:** both IAM users went, with their keys, console password and MFA, along
  with the `admins` group. The Codespaces and Actions secrets were already gone.
- **The rest of the account went too**, at the owner's request: schedule-ai-app
  (unused since 2026-08-26), 2025 leftovers (SageMaker, CodeBuild/CodePipeline,
  RDS and App Runner roles, their log groups), two unrelated buckets, and
  `beer7.click`: SES identities, DNS records, hosted zone and the domain
  registration. Its Anthropic API key, readable in its old state, was revoked.
  No custom IAM role, policy, user or OIDC provider is left.
- **9e** the same day, at the owner's request: production's media was copied
  to the codespace first (`~/bgucats-media-backup`, 1,239 objects, byte count
  equal to the bucket), then the old table, lock table and the three buckets
  were deleted. Production checked afterwards: table `ACTIVE` with deletion
  protection, media unchanged. That copy lives only as long as the codespace;
  download it to a computer.

What remains in `851725214678`: Organizations, Identity Center (and its KMS
key), the budgets, and the 9b backup.

### 9a. Last checks

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
aws sso login --profile mgmt-admin --use-device-code
python scripts/migrate_account.py verify            # "missing" must be 0, except TRAFFIC# (see 8.4)
aws dynamodb describe-continuous-backups --table-name bgucats-data --profile bgucats-prod-ro \
  --query ContinuousBackupsDescription.PointInTimeRecoveryDescription.PointInTimeRecoveryStatus   # ENABLED
aws dynamodb describe-table --table-name bgucats-data --profile bgucats-prod-ro --query Table.DeletionProtectionEnabled   # true
```

`verify` ends with `DIFFERENCES`, and that is expected: new work in the new
account, and under SSM the bot token and webhook secret `differ` because they
were rotated on 2026-10-31. The salt must say `same`.

Recommended before 9e: a copy outside AWS altogether, on your own computer
rather than the codespace (which goes when its machine does). A few GB:
`aws s3 sync s3://bgucats-media-395591097129 ./bgucats-media --profile bgucats-prod-ro`.

### 9b. A final backup of the old table

```bash
aws dynamodb create-backup --profile mgmt-admin --table-name bgucats-data --backup-name bgucats-data-before-decommission
```

An on-demand backup outlives the table it came from and costs cents a
month. Keep it.

### 9c. Destroy the old app, keeping the data

`terraform destroy` against the old state, after taking the table, the
media bucket and the web bucket (which holds the model) out of Terraform's
hands, so that the destroy cannot reach them. This is a one-time owner run
by hand. It uses its own data directory, so the codespace's init for the
new account is not touched:

```bash
cd /workspaces/BGUcats && git checkout main && git pull --ff-only && make build
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
export AWS_PROFILE=mgmt-admin TF_DATA_DIR=$HOME/.tf-old-account
aws sts get-caller-identity --query Account --output text          # 851725214678
terraform -chdir=infra/main init -reconfigure -backend-config="bucket=bgucats-tfstate-851725214678"
for a in aws_dynamodb_table.data aws_dynamodb_table_item.bootstrap_admin \
         aws_s3_bucket.media aws_s3_bucket_versioning.media \
         aws_s3_bucket_server_side_encryption_configuration.media \
         aws_s3_bucket_public_access_block.media aws_s3_bucket_lifecycle_configuration.media \
         aws_s3_bucket.web aws_s3_bucket_server_side_encryption_configuration.web \
         aws_s3_bucket_public_access_block.web; do
  terraform -chdir=infra/main state rm "$a"
done
```

The state bucket is versioned, so the state from before these `state rm`s
is still there as an older version. A `state rm` that says `No matching objects`
is fine: that resource was never in the old state. Then plan the destroy. The
variable needs some value, since nothing is created:

```bash
export TF_VAR_bootstrap_admin_email=destroy@example.com
terraform -chdir=infra/main plan -destroy -out=destroy.tfplan
terraform -chdir=infra/main show -no-color destroy.tfplan \
  | grep -E '# aws_(dynamodb_table\.data|s3_bucket\.(media|web)) ' && echo "STOP: data is in the plan" || echo "data not in the plan"
```

It must say `data not in the plan` and `0 to add, 0 to change, N to
destroy`. What it destroys: the Lambdas (the old WhatsApp bot's too, which
the code no longer has but the old state does) and their roles, the API, both
distributions, the user pool with its `bgucats-admin` domain, the site
bucket, the app's files, the SSM parameters, Google's identity provider, and the
media bucket's CORS rule and S3 → Lambda notification. The `removed` blocks in
`ssm.tf` and `cognito.tf` do not protect these: a destroy plan ignores them
(tested 2026-11-02), and the old state still has them.

If the apply stops on `BucketNotEmpty`, empty the site bucket in the console and
run the plan and apply again. Its session lasts an hour, so sign in just before.

```bash
terraform -chdir=infra/main apply destroy.tfplan          # CloudFront takes 15+ minutes
rm infra/main/destroy.tfplan; unset AWS_PROFILE TF_DATA_DIR TF_VAR_bootstrap_admin_email
```

**The QR codes on the posters stop working here**, as accepted: they encode
the old site distribution.

Then remove the old bootstrap resources, which are in no state file the
codespace has. First check that nothing but bgucats trusts the provider:

```bash
aws iam list-roles --profile mgmt-ro --query "Roles[?contains(to_string(AssumeRolePolicyDocument), 'token.actions.githubusercontent.com')].RoleName"
# expect only bgucats-github-actions-ci
for p in bgucats-kms-list-aliases bgucats-tfstate-read bgucats-plan-read-infra-main; do
  aws iam delete-role-policy --profile mgmt-admin --role-name bgucats-github-actions-ci --policy-name "$p"
done
aws iam delete-role --profile mgmt-admin --role-name bgucats-github-actions-ci
aws iam delete-open-id-connect-provider --profile mgmt-admin \
  --open-id-connect-provider-arn arn:aws:iam::851725214678:oidc-provider/token.actions.githubusercontent.com
```

The old state bucket and lock table stay, with the data, until 9e. In
Google's OAuth client, remove the old `bgucats-admin` redirect URI.

Terraform never managed the Lambdas' log groups, so delete them by hand, then
look at what is left. Only the data from 9e and anything that is not bgucats
should remain:

```bash
for g in $(aws logs describe-log-groups --log-group-name-prefix /aws/lambda/bgucats --profile mgmt-ro \
             --query 'logGroups[].logGroupName' --output text); do
  aws logs delete-log-group --log-group-name "$g" --profile mgmt-admin
done
aws ssm get-parameters-by-path --path /bgucats --recursive --profile mgmt-ro --query 'Parameters[].Name'
aws lambda list-functions --profile mgmt-ro --query 'Functions[].FunctionName'
aws cloudfront list-distributions --profile mgmt-ro --query 'DistributionList.Items[].DomainName'
aws cognito-idp list-user-pools --max-results 20 --profile mgmt-ro --query 'UserPools[].Name'
aws s3 ls --profile mgmt-ro
```

### 9d. Keys, the old IAM user, schedule-ai-app

1. **GitHub:** repo → *Settings* → *Secrets and variables* → **Codespaces**:
   delete `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and
   `TELEGRAM_BOT_TOKEN`. The bot token now lives in SSM and in the
   `production` environment, and every codespace can read a Codespaces
   secret. Do the same under **Actions** → *Repository secrets* (any
   `AWS_*`), and at <https://github.com/settings/codespaces> (any `AWS_*`
   with access to `BGUcats`). Restart the codespace:
   `env | grep '^AWS_ACCESS'` prints nothing.
2. **schedule-ai-app** has its own IAM user (`schedule-ai-terraform`).
   Tear it down from its own repo before item 3. First confirm that it
   never used `sasha-bgucats-admin` (`aws sts get-caller-identity` in its
   codespace).
3. **The keys** of `sasha-bgucats-admin`. First see what they were last used
   for. A use after 2026-10-30 means something still depends on them: find out
   what before going on.

   ```bash
   for k in $(aws iam list-access-keys --user-name sasha-bgucats-admin --profile mgmt-ro \
                --query 'AccessKeyMetadata[].AccessKeyId' --output text); do
     aws iam get-access-key-last-used --access-key-id "$k" --profile mgmt-ro \
       --query '[AccessKeyLastUsed.LastUsedDate,AccessKeyLastUsed.ServiceName]' --output text
   done
   ```

   Then console (as `mgmt-admin`) → *IAM* → *Users* → *Security credentials* →
   each key → **Deactivate**, then **Delete**, then **delete the user**. Its login profile, its
   MFA device `arn:aws:iam::851725214678:mfa/iphone` and its group
   membership go with it. Root and Identity Center remain as the ways in.

### 9e. Last: the old data

Planned for 30 days after 9c. This is the only other copy of the photos, and
deleting it leaves production as the only one, so take the copy from 9a first.
Only after running 9a's `verify` again that day, with `missing` = 0
everywhere but `TRAFFIC#`. If the table has deletion protection on, turn it off:
`aws dynamodb update-table --table-name bgucats-data --no-deletion-protection-enabled --profile mgmt-admin`.
Then, in the console as `mgmt-admin`: *DynamoDB* →
`bgucats-data` → **Delete**. Keep the 9b backup; it is not deleted with the
table. *S3* → `bgucats-media-851725214678`, `bgucats-admin-web-851725214678`,
`bgucats-tfstate-851725214678` → **Empty** (this removes every version) →
**Delete**. *DynamoDB* → `bgucats-tfstate-lock` → **Delete**.

---

## 10. Guardrails on member accounts (SCPs)

Any time after step 6d has deployed once. Service control policies never
apply to the management account, only to members.
`infra/org/scp-member-guardrails.json` is one policy with three statements:
stay in the organization, no IAM users or access keys, no region but
`us-east-1`. Following AWS's own example, the region rule uses `NotAction`
to exempt the global services (IAM, STS, CloudFront, Organizations, Support,
billing and others). Without that, CloudFront and IAM would break.

First see what is there. If `bgucats-member-guardrails` is already listed, it
has been applied: skip to the checks below. Every account listed will be
covered, so anything other than the management account and
`sasha-bgucats-prod` needs a look first.

```bash
aws organizations list-policies --filter SERVICE_CONTROL_POLICY --profile mgmt-ro --query 'Policies[].Name'
aws organizations list-accounts --profile mgmt-ro --query 'Accounts[].[Id,Name,Status]' --output table
```

Then, from the repo root (`enable-policy-type` says
`PolicyTypeAlreadyEnabledException` if SCPs are already on; that is fine):

```bash
export AWS_PROFILE=mgmt-admin
ROOT=$(aws organizations list-roots --query 'Roots[0].Id' --output text)
aws organizations enable-policy-type --root-id "$ROOT" --policy-type SERVICE_CONTROL_POLICY
POLICY=$(aws organizations create-policy --type SERVICE_CONTROL_POLICY --name bgucats-member-guardrails \
  --description "Stay in the org; no IAM users or access keys; us-east-1 only" \
  --content file://infra/org/scp-member-guardrails.json --query Policy.PolicySummary.Id --output text)
aws organizations attach-policy --policy-id "$POLICY" --target-id "$ROOT"
unset AWS_PROFILE
```

It is attached to the root, so it covers every member account, including
any made later. AWS's `FullAWSAccess` stays attached: SCPs only take
permissions away. Check it:

```bash
# A key for a user that does not exist: denied with the SCP, NoSuchEntity
# without it. Either way nothing is created (create-user would create one
# if the SCP were not working).
aws iam create-access-key --user-name scp-test-no-such-user --profile bgucats-prod-admin   # AccessDenied
aws ec2 describe-vpcs --region eu-west-1 --profile bgucats-prod-ro              # denied: explicit deny in a service control policy
aws ec2 describe-vpcs --region us-east-1 --profile bgucats-prod-ro --query 'length(Vpcs)'   # works
```

Then run **Deploy** with `plan_only`: `No changes.`

**Way back,** if something in production is refused. It takes effect within
minutes and deletes nothing:

```bash
ROOT=$(aws organizations list-roots --profile mgmt-admin --query 'Roots[0].Id' --output text)
POLICY=$(aws organizations list-policies --filter SERVICE_CONTROL_POLICY --profile mgmt-admin \
  --query "Policies[?Name=='bgucats-member-guardrails'].Id" --output text)
aws organizations detach-policy --policy-id "$POLICY" --target-id "$ROOT" --profile mgmt-admin
```

**Optional, recommended: central root access.** Member accounts created in
Organizations have a root user with no password, but anyone with the
account's email inbox can reset one. This lets the management account
delete member root credentials:

```bash
aws organizations enable-aws-service-access --service-principal iam.amazonaws.com --profile mgmt-admin
aws iam enable-organizations-root-credentials-management --profile mgmt-admin
aws iam enable-organizations-root-sessions --profile mgmt-admin
```

Then console → *IAM* → *Root access management* → `sasha-bgucats-prod` →
**Delete root user credentials**.

---

## 11. Move the repo to `ARIP-org` (Phase 2a)

The organization `ARIP-org` (ID 353802310) was created on 2026-11-07, on
GitHub Team. The repo keeps its ID (1339652949) through a transfer, but its
name in GitHub's tokens changes, and AWS trusts tokens by name. So, in this
order: AWS learns the new name, then the transfer, then the checks, then AWS
forgets the old name.

**Done on 2026-11-07, 11e included.** Both roles trust only
`ARIP-org/BGUcats` (checked with `aws iam get-role` after the apply).
**11a–11d:** The apply changed 3 resources as planned
(#32, merged before the transfer). After the transfer: the `production`
environment with its `main` rule, the `main` ruleset (no bypass, checks
`python` + `terraform`), auto-delete of head branches and Dependabot's
updates were all there. Variables and secrets are proven by 11e's CI run and
deploy, which fail by name if one is missing.

### 11a. Apply the bootstrap PR from its branch, then merge it

The PR "Bootstrap: trust ARIP-org/BGUcats too" adds the new name to both
roles' trust and takes the lock writes away from the CI role. Merging it
does not apply it: `infra/bootstrap` is applied by hand
(`infra/README.md`). From the codespace:

```bash
cd /workspaces/BGUcats && git fetch origin && git checkout bootstrap-trust-arip-org && git pull --ff-only
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
aws sso login --profile bgucats-prod-admin --use-device-code
infra/scripts/bootstrap-apply.sh
```

It must show `Plan: 0 to add, 3 to change, 0 to destroy`: the two roles'
trust policies (`sasha720709/BGUcats` → both names) and the CI role's
`bgucats-tfstate-read` (lock: GetItem only). Type `yes`. It ends with
`Apply complete! Resources: 0 added, 3 changed, 0 destroyed.` and copies the
state to the bucket. Then:

```bash
git checkout main
```

and merge the PR. Its CI passes before and after the apply alike, since the
old name stays trusted. The deploy of the merge says `No changes.`

### 11b. Before the transfer

1. **Download `~/bgucats-media-backup`** from the codespace to a computer
   (VS Code explorer → right-click → *Download*). A codespace may have to be
   created again after the transfer, and this copy would go with the old one.
2. **Push everything.** No work only in the codespace.
3. **Codespaces in the organization:** `ARIP-org` → *Settings* →
   *Codespaces*: allow them for you (all members, or you selected) and look
   at who pays. If a new codespace for `ARIP-org/BGUcats` can't be created
   after the transfer, this is where to look.

### 11c. The transfer

Repo → *Settings* → *General* → bottom, *Danger Zone* → **Transfer** →
*Select one of my organizations* → `ARIP-org` → type `sasha720709/BGUcats`
to confirm → **I understand, transfer this repository**. Old URLs, clones
and `git` remotes are redirected. In the codespace, all the same:

```bash
git remote set-url origin https://github.com/ARIP-org/BGUcats.git && git fetch origin
```

### 11d. Right after: check what came across

GitHub's transfer docs promise secrets and webhooks, not environments,
variables or rulesets. Claude can read most of these; what it can't, you
check in *Settings*:

| What | Expect | If missing |
|---|---|---|
| *Environments* → `production` → deployment branches | **Selected**, one rule: `main` | 5a. **Before any merge**: this is what limits the deploy role to `main` |
| *Secrets and variables* → *Actions* → *Variables* | repo `AWS_CI_ROLE_ARN`; environment `production`: `AWS_DEPLOY_ROLE_ARN` | 5b, with `R=ARIP-org/BGUcats` |
| Environment `production` → secrets | `BOOTSTRAP_ADMIN_EMAIL` | below |
| *Rules* → *Rulesets* | `main`, Active, no bypass: deletions, force pushes, PR, checks `python` + `terraform` | 5e |
| *General* | *Automatically delete head branches* on | tick it |
| *Code security* | Dependabot alerts and version updates on | turn on |

`BOOTSTRAP_ADMIN_EMAIL`, if missing, from production's table:

```bash
env -u GITHUB_TOKEN gh auth login --hostname github.com --git-protocol https --web
aws dynamodb query --profile bgucats-prod-ro --table-name bgucats-data --index-name GSI2 \
  --key-condition-expression 'GSI2PK = :a' --filter-expression 'addedBy = :t' \
  --expression-attribute-values '{":a":{"S":"ENTITY#ADMIN"},":t":{"S":"terraform"}}' \
  --query 'Items[0].email.S' --output text | tr -d '\n' \
  | env -u GITHUB_TOKEN gh secret set BOOTSTRAP_ADMIN_EMAIL --env production -R ARIP-org/BGUcats
```

### 11e. Prove it, then drop the old name

Claude opens one more bootstrap PR: only `ARIP-org/BGUcats` in
`github_repos`, and the docs moved to the new name. **Its CI run is the
proof for the CI role** (`terraform` passes, so the new token was accepted).
Apply it as in 11a (`Plan: 0 to add, 2 to change, 0 to destroy`), then
merge: **its Deploy is the proof for the deploy role**. Until then the old
name is still trusted, so do this the same day. A repo created again as
`sasha720709/BGUcats` would be trusted too while it is.

**How it went (2026-11-07):** PR #34's CI and its merge's Deploy passed;
the apply ran from a new codespace afterwards, at 17:47 UTC, once the owner
could sign in (`docs/codespaces.md`, "When the device page hangs"). Its
first plan also wanted to update the budget: a pasted `export` had split
across two lines and put the whole state into `TF_VAR_budget_alert_email`.
Nothing was applied; `bootstrap-apply.sh` now takes the address from the
state and refuses anything that is not one address.

---

## 12. The staging account (Phase 2b)

A second copy of the app in an account of its own, so every change is seen
before users see it (`docs/ROADMAP.md`, 2b). Decided 2026-11-07: **no
Telegram bot** in staging (it is on its way out), **a separate Google OAuth
client** (beta access will be managed apart from production), never real
contributor photos.

| | |
|---|---|
| Account | `586943192664` `bgucats-staging`, root email `sashajewishman+bgucats-staging@gmail.com` (no root password) |
| SSO profiles | `bgucats-staging-ro`, `bgucats-staging-admin` |
| State bucket | `bgucats-tfstate-586943192664` (`infra/main/backend/staging.hcl`), made by step 12c |
| Cognito domain | `bgucats-staging` |

### 12a. Create the account — done 2026-11-07

Claude ran it in the owner's session, at the owner's request:

```bash
export AWS_PROFILE=mgmt-admin
aws organizations create-account --email sashajewishman+bgucats-staging@gmail.com \
  --account-name bgucats-staging --query CreateAccountStatus.Id --output text
# then describe-create-account-status until SUCCEEDED (about 2 minutes)
```

It sits under the root (`r-6978`), so both SCPs apply (checked: a call to
`eu-west-1` is an explicit deny). The owner's user `Sasha` got
ReadOnlyAccess and AdministratorAccess on it, directly, as on production
(`aws sso-admin create-account-assignment`, principal type `USER`). **The
first assignment failed** with `InvalidClientTokenId`: the account was
seconds old and its IAM was not ready. Run again, it succeeded. Then:
`alias/aws/ssm` described once (6a's reason), Lambda concurrency 10 (enough:
staging copies no data and nothing reserves concurrency). AWS sent no
welcome email; accounts created inside an organization often get none.

The profiles, in `~/.aws/config`:

```ini
[profile bgucats-staging-ro]
sso_session = sasha
sso_account_id = 586943192664
sso_role_name = ReadOnlyAccess
region = us-east-1
[profile bgucats-staging-admin]
sso_session = sasha
sso_account_id = 586943192664
sso_role_name = AdministratorAccess
region = us-east-1
```

### 12b. `infra/main` for two accounts — the PR "Staging: infra/main for two accounts"

Production's plan: the bot's 7 resources move to `[0]`, nothing else.
A plan of the empty staging account (read-only, local state, 2026-11-07):
78 to add, no bot, domain `bgucats-staging` (free that day).

### 12c. Bootstrap the staging account

The PR "Staging: bootstrap per account" gives `infra/bootstrap` a variable
`environment` (the deploy role trusts `…:environment:<it>`), and keeps
its local state per account, in `infra/bootstrap/state/<account>.tfstate`.
The first run there moves the old `infra/bootstrap/terraform.tfstate` if it is
that account's. Production's plan on that branch: `No changes`.

From that PR's branch:

```bash
cd /workspaces/BGUcats && git fetch origin && git checkout staging-bootstrap && git pull --ff-only
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
aws sts get-caller-identity --profile bgucats-staging-admin --query Arn --output text
export TF_VAR_budget_alert_email=sashajewishman@gmail.com
export AWS_PROFILE=bgucats-staging-admin
infra/scripts/bootstrap-apply.sh --first
```

It must say `aws-guard: staging, account 586943192664` and
`No state yet: a first bootstrap of account 586943192664 (staging)`, then
`Plan: 18 to add, 0 to change, 0 to destroy`: the state bucket (4), the
lock table, the OIDC provider, the CI role (4), the boundary, the deploy
role (6) whose trust ends in `:environment:staging`, and the budget. Type
`yes`. It ends with `Saved: s3://bgucats-tfstate-586943192664/…`. Then:

```bash
unset AWS_PROFILE TF_VAR_budget_alert_email
AWS_PROFILE=bgucats-prod-admin infra/scripts/bootstrap-apply.sh   # production: No changes
git checkout main
```

and merge the PR. Its CI only formats and validates bootstrap.

### 12d. Google: a client of staging's own

Done 2026-11-07, by the owner: a Google Cloud project `bgucats-staging` of
its own, so its consent screen's *Test users* is staging's beta list,
apart from production's. Consent screen External, in Testing; a Web
application client `bgucats-staging-cognito`, no JavaScript origins, one
redirect URI:

```
https://bgucats-staging.auth.us-east-1.amazoncognito.com/oauth2/idpresponse
```

Cognito gets it after the first staging deploy has made the user pool (12f).

**No salt in staging:** only the Telegram ingest Lambda reads
`/bgucats/submitter-hash-salt`, and staging has no bot.

### 12e–12g

Next: the GitHub environment `staging`, the deploy and promote workflows,
seed data. Written here as each one is done.

---

## Known gap: the CI role can read production secrets

CI runs `terraform plan` on every PR, and a PR runs **its own** copy of
`ci.yml`. So anyone who can push a branch to this repo — including a Claude
Code session with your GitHub token — can make the CI role do whatever it
is allowed to. It cannot change anything in AWS. Until 2026-10-31 it could
read every secret, two ways:

1. **Through the state.** Terraform state held the Telegram token, the
   webhook secret, the salt and the Google client secret in clear text.
   **Closed** by the PR "Secrets out of Terraform": Terraform no longer
   manages them (`infra/scripts/set-secret.sh` does, `docs/deploy.md`).
   Older copies of the state stay in the versioned state bucket, which the
   CI role cannot read (`s3:GetObject` only, no `GetObjectVersion`).
2. **Directly.** The CI role had `ssm:GetParameter` on the three
   parameters and `cognito-idp:DescribeIdentityProvider`, both needed only
   while Terraform refreshed them. **Closed** by the bootstrap PR "CI and
   deploy roles: no access to secrets", once applied
   (`infra/scripts/bootstrap-apply.sh`). The deploy role lost its SSM and
   Google-provider actions in the same change.

After both: rotate what was readable — the bot token (`/revoke` in
@BotFather), the webhook secret and the Google client secret, each with
`set-secret.sh`. Not the salt: a new salt makes every Telegram contributor
a new person, and it only matters to someone who also has the table.

---

## How you work from now on

- **Change anything:** a branch → PR → CI runs ruff, pytest and `terraform
  plan` → read the plan → merge. The merge deploys. Nobody runs `terraform
  apply` on `infra/main`.
- **Roll back:** `git revert -m 1 <merge commit>` on a branch → PR → merge
  (`docs/deploy.md` → Rollback). Old production states are tagged
  `rollback/*`.
- **SSO admin** (`bgucats-prod-admin`, one-hour sessions) only for:
  `infra/bootstrap` (before the PR that needs a wider deploy role or
  boundary), `make model-publish PROFILE=bgucats-prod-admin`,
  `make admin-add` with the same `PROFILE`, and
  break-glass. `mgmt-admin` only for Identity Center, Organizations and
  billing.
- **Everything else read-only:** `bgucats-prod-ro`. A Claude session uses
  the read-only profiles by default, and an admin profile only for a job the
  owner asked for, in the owner's session (`CLAUDE.md`, "Workflow").
