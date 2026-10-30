# Manual steps: bgucats moves to its own account, deployed only by GitHub

Everything in the move that code cannot do. Written 2026-10-30, for the owner.
Do the steps **in order**. Each one says what breaks if it is skipped or done
out of order. The order is chosen so that the old account keeps running
production, untouched, until the new one has been proven, and so that no
step can lose the dataset.

| | |
|---|---|
| Old account | `851725214678`: production today; becomes the organization's management account and ends up running nothing |
| New account | `395591097129` `sasha-bgucats-prod`: production after step 8 |
| Region | `us-east-1` |
| SSO profiles | `mgmt-ro`, `mgmt-admin` (old account), `bgucats-prod-ro`, `bgucats-prod-admin` (new) |
| Repo | `sasha720709/BGUcats` (owner ID 254865293, repo ID 1339652949) |
| CI role | `arn:aws:iam::395591097129:role/bgucats-github-actions-ci` |
| Deploy role | `arn:aws:iam::395591097129:role/bgucats-github-actions-deploy` |
| Cognito domain | `bgucats-app` (old: `bgucats-admin`) |
| Old user pool | `us-east-1_iLd1I4gJ9` |
| Old IAM user | `sasha-bgucats-admin` (group `admins` → AdministratorAccess), keys ending `…F4MF` and `…IITS` |

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
aws sso login --sso-session bgucats --use-device-code
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
2. *Required reviewers* → `sasha720709`, and untick *Prevent self-review*.
   Recommended during the move. Every deploy then waits for your click.

### 5b. Variables (the role ARNs, not secrets)

```bash
env -u GITHUB_TOKEN gh auth login --hostname github.com --git-protocol https --web
alias ghx='env -u GITHUB_TOKEN gh'
R=sasha720709/BGUcats
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
   - CloudFront: *"Your account must be verified before you can add new
     CloudFront resources"*. This happens to some new accounts. Open a
     support case (*Account and billing*, free), then re-run.
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

### Way back, until step 9

The old account is complete and still running. Point Telegram back at it
(`setWebhook` with the URL written down in 7b.2 and the same
`secret_token`), and use the old app. Work
done in the new account in the meantime can be copied back with the same
script, accounts reversed:
`--source-profile bgucats-prod-ro --source-account 395591097129 --dest-profile mgmt-admin --dest-account 851725214678`.

---

## 9. Decommission the old account

**Not before two weeks of the new account working**, and in this order.
Everything before 9e can be undone.

### 9a. Last checks

```bash
python scripts/migrate_account.py verify            # "missing" must be 0 everywhere
aws dynamodb describe-continuous-backups --table-name bgucats-data --profile bgucats-prod-ro \
  --query ContinuousBackupsDescription.PointInTimeRecoveryDescription.PointInTimeRecoveryStatus   # ENABLED
aws dynamodb describe-table --table-name bgucats-data --profile bgucats-prod-ro --query Table.DeletionProtectionEnabled   # true
```

Optional, recommended: a copy outside AWS altogether, on your own computer
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
is still there as an older version. Then plan the destroy. The variables
need some value, since nothing is created:

```bash
for v in telegram_bot_token telegram_webhook_secret submitter_hash_salt google_client_id google_client_secret; do export TF_VAR_$v=destroy; done
export TF_VAR_bootstrap_admin_email=destroy@example.com
terraform -chdir=infra/main plan -destroy -out=destroy.tfplan
terraform -chdir=infra/main show -no-color destroy.tfplan \
  | grep -E '# aws_(dynamodb_table\.data|s3_bucket\.(media|web)) ' && echo "STOP: data is in the plan" || echo "data not in the plan"
```

It must say `data not in the plan` and `0 to add, 0 to change, N to
destroy`. What it destroys: the Lambdas (the old WhatsApp bot's too, which
the code no longer has but the old state does) and their roles, the API, both
distributions, the user pool with its `bgucats-admin` domain, the site
bucket, the app's files, the SSM parameters, and the media bucket's CORS
rule and S3 → Lambda notification.

```bash
terraform -chdir=infra/main apply destroy.tfplan          # CloudFront takes 15+ minutes
rm destroy.tfplan; unset AWS_PROFILE TF_DATA_DIR $(env | grep -o '^TF_VAR_[a-z_]*')
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
3. **The keys** of `sasha-bgucats-admin`: console (as `mgmt-admin`) →
   *IAM* → *Users* → *Security credentials* → each key → **Deactivate**.
   Wait a day or two and look at *Last used*. If nothing broke,
   **Delete** each key, then **delete the user**. Its login profile, its
   MFA device `arn:aws:iam::851725214678:mfa/iphone` and its group
   membership go with it. Root and Identity Center remain as the ways in.

### 9e. 30 days later: the old data

Only after running 9a's `verify` again that day, with `missing` = 0
everywhere. Then, in the console as `mgmt-admin`: *DynamoDB* →
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
aws iam create-user --user-name scp-test --profile bgucats-prod-admin           # AccessDenied ... service control policy
aws ec2 describe-vpcs --region eu-west-1 --profile bgucats-prod-ro              # AccessDenied ... service control policy
aws ec2 describe-vpcs --region us-east-1 --profile bgucats-prod-ro --query 'length(Vpcs)'   # works
```

Then run **Deploy** with `plan_only`: `No changes.`

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

## Known gap: the CI role can read production secrets

This is not new, and the move does not fix it. CI runs `terraform plan` on
every PR, and a PR runs **its own** copy of `ci.yml`. The plan needs the
state file, and Terraform state holds every secret in clear text: the
Telegram token, the webhook secret, the salt and the Google client secret.
So anyone who can push a branch to this repo can write a workflow that reads
them through the CI role. That includes a Claude Code session with your
GitHub token. It cannot change anything in AWS, but it can read those
values.

Ways to close it, in order of effort:

1. Make the secrets *write-only* in Terraform (`value_wo` on
   `aws_ssm_parameter`, Terraform ≥ 1.11), so they never enter state. The
   Google client secret needs the same, or to be set outside Terraform the
   way the WhatsApp secrets were.
2. Until then, keep push access to yourself, and read any Claude session's
   PR that edits `.github/workflows/` before its checks run.

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
- **Everything else read-only:** `bgucats-prod-ro`. It is the only profile
  a Claude session may ever be handed.
