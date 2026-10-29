# Manual steps: main-only, OIDC deploys, no AWS keys

Everything in the move to "`main` is production, deployed by GitHub Actions
with OIDC" that code cannot do. Written 2026-10-29, for the owner. Do the
steps **in order**. Each one says what breaks if it is skipped or done out of
order. The order is chosen so that production is never broken, and the old
admin key is removed only after its replacement has worked.

Real names used below:

| | |
|---|---|
| AWS account | `851725214678`, region `us-east-1` |
| Repo | `sasha720709/BGUcats` (owner ID 254865293, repo ID 1339652949) |
| Deploy role | `arn:aws:iam::851725214678:role/bgucats-github-actions-deploy` |
| CI role | `arn:aws:iam::851725214678:role/bgucats-github-actions-ci` |
| Boundary | `arn:aws:iam::851725214678:policy/bgucats-lambda-permissions-boundary` |
| OIDC provider | `arn:aws:iam::851725214678:oidc-provider/token.actions.githubusercontent.com` |
| Old admin user | `sasha-bgucats-admin` (group `admins` → AdministratorAccess), two access keys ending `…F4MF` and `…IITS` |

**Checked before writing this (read-only, with the old admin key):**
`consolidate-main` matches production. A plan against live state showed only
the Lambda code hashes, and the deployed source is byte-identical to the
tree. The difference is zip noise, fixed in PR 2. The bootstrap plan and all
of the new IAM policies were checked with `iam:SimulateCustomPolicy`: the
reads that a plan makes, the writes an apply needs, 37 things the deploy
role must be refused, and every action the Lambdas use against the boundary.
Nothing was applied.

---

## 1. IAM Identity Center first, so you are never locked out

Identity Center can only give console and CLI access to an AWS account
(permission sets) from an *organization* instance, enabled in an AWS
Organizations management account. In a standalone account you get an
"account instance", which cannot do that ([AWS docs, instance comparison
table](https://docs.aws.amazon.com/singlesignon/latest/userguide/identity-center-instances.html)).
So the organization comes first. It is created **in `851725214678`
itself**: that account becomes the organization's management account.
Nothing moves, and no new account or card is needed.

What that means, and what it does not:

- **Nothing moves or changes.** bgucats, schedule-ai-app, IAM, the old keys
  and the bill all stay exactly where they are. "Creating an
  organization" puts a container around the account; it does not copy or
  migrate anything.
- **This account is the management account for good.** AWS does not let
  you hand that role to another account later. The only way out is to
  remove every member and delete the organization.
- **Service control policies never apply to the management account.** So
  guardrails like "nobody may create access keys" can only bind member
  accounts, such as a future staging account, never this one. For one
  person, IAM Identity Center plus the deploy role's own limits cover that.
- **New accounts become cheap.** Member accounts are created from the
  console, billed to this account's card, with no signup. That is how a
  separate staging account would be made, if you want one.

### 1a. Create the organization

1. Sign in to `851725214678` as root, or as `sasha-bgucats-admin` (it has
   AdministratorAccess, which is enough).
2. Console search → **AWS Organizations** → **Create an organization**.
   Leave *all features* on.
3. AWS emails the account's root address a verification link. Click it.
   Some organization actions wait for that.

### 1b. Enable Identity Center and create your user

Still in `851725214678`, region selector at the top right = **US East
(N. Virginia) us-east-1**:

1. Console search → **IAM Identity Center** → **Enable** → *Enable with AWS
   Organizations*. Identity source: the default, *Identity Center
   directory*.
2. *Settings* → *Authentication* → *Multi-factor authentication* →
   **Configure**: prompt *Every time they sign in*; types *Security keys
   and built-in authenticators* and *Authenticator apps*; if a user has no
   MFA device, *Require them to register an MFA device at sign in*. Save.
3. *Users* → **Add user**: username `sasha`, your normal email address,
   *Send an email to this user with password setup instructions*. Open the
   email, set the password, sign in to the access portal, and register
   MFA when it asks.
4. Write down the **AWS access portal URL** (*Dashboard* → *Settings
   summary*, `https://d-xxxxxxxxxx.awsapps.com/start`).

### 1c. Permission sets and assignment

1. *Permission sets* → **Create permission set** → *Predefined* →
   `AdministratorAccess` → session duration **1 hour** → Create.
2. Again: *Predefined* → `ReadOnlyAccess` → session duration **8 hours**.
3. *AWS accounts* → tick `851725214678` → **Assign users or groups** →
   *Users* → `sasha` → Next → tick **both** permission sets → Submit. Wait
   until it says the assignment is provisioned (it creates
   `AWSReservedSSO_*` roles in `851725214678`).

### 1d. Use it from the codespace

The codespace still has the old keys as environment variables, and those
win over a profile set with `AWS_PROFILE`. So for now, pass `--profile`
explicitly, or unset the keys in that shell:

```bash
aws configure sso --use-device-code   # session "bgucats", the portal URL above,
                                      # region us-east-1, role AdministratorAccess,
                                      # profile name bgucats-admin
aws configure sso --use-device-code   # same session, role ReadOnlyAccess,
                                      # profile name bgucats-readonly
aws sts get-caller-identity --profile bgucats-admin
aws sts get-caller-identity --profile bgucats-readonly
```

Both must print `arn:aws:sts::851725214678:assumed-role/AWSReservedSSO_<set>_<hash>/sasha`.
Field-by-field answers to the prompts: `docs/codespaces.md` → "AWS access".

**If skipped:** step 4 has no way to run except the old key, and once step 6
deletes the key there is no admin access to the account except root.
**If done after step 6:** you are locked out of IAM-user admin access with
nothing to replace it. Root still works, but that is the emergency door,
not the daily one.

---

## 2. Merge PR 1, tag the old branch heads, delete the stack

1. Open **PR 1 "Make main the production branch"** (`consolidate-main` →
   `main`). Expect its `python` check to pass. Its `terraform` check fails
   the same way `main` has failed since 2026-10-29: the live CI role lacks
   read permissions for the newer resources. Step 4 fixes that.
2. Merge with **"Create a merge commit"**, not squash, so `main`'s history
   keeps the whole stack and the tags below stay reachable from `main`.
3. Tag the old heads so every previous production state can still be
   checked out, then push the tags:

```bash
cd /workspaces/BGUcats
git fetch origin
git checkout main && git pull --ff-only
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

All five must print `ok`. Only then delete the branches:

```bash
git push origin --delete admin-labeling-tool app-preprod recognition-labeling claude/hopeful-feynman-l098o2
git branch -D admin-labeling-tool app-preprod recognition-labeling claude/hopeful-feynman-l098o2
```

4. Delete `consolidate-main` with the button on the merged PR. GitHub then
   retargets PR 2 to `main` by itself. If it does not, use *Edit* next to
   PR 2's title → base `main`.

**If skipped:** nothing in production breaks. `main` simply isn't
production, so PR 2's pipeline would deploy an older app (`main` is 31
commits behind) the moment it applies. That is the one ordering mistake
here that would take features away from users. **Deleting branches before
the tags are pushed** loses the only names for those production states. The
commits remain reachable from `main` after a merge commit, but not after a
squash.

---

## 3. GitHub settings: environment, secrets, branch rules

**This must happen before step 4.** GitHub creates an environment that a
workflow names, with **no** protection, the first time a job uses it. If
the deploy role exists while `production` is unprotected, a workflow on any
branch, including one pushed by a Claude session, could declare
`environment: production` and assume the deploy role.

### 3a. Environment `production`

Repo → *Settings* → *Environments* → **New environment** → `production` →
Configure:

1. *Deployment branches and tags* → **Selected branches and tags** → *Add
   deployment branch or tag rule* → Ref type *Branch* → `main`.
2. Optional: *Required reviewers* → `sasha720709`, and untick *Prevent
   self-review*. Every deploy, plan-only ones included, then waits for
   your click. Recommended during this migration; you can remove it once
   deploys are routine.

### 3b. Environment secrets

These are infra/main's six variables. Values come from what is live, so the
first plan shows no change. **Do not type them.** Pipe them from AWS into
`gh`, which never prints them. The codespace's own `GITHUB_TOKEN` cannot
write secrets, so log `gh` in as yourself first:

```bash
env -u GITHUB_TOKEN gh auth login --hostname github.com --git-protocol https --web
alias ghx='env -u GITHUB_TOKEN gh'
R=sasha720709/BGUcats
p()   { aws ssm get-parameter --profile bgucats-admin --with-decryption --name "$1" --query Parameter.Value --output text | tr -d '\n'; }
idp() { aws cognito-idp describe-identity-provider --profile bgucats-admin --user-pool-id us-east-1_iLd1I4gJ9 \
          --provider-name Google --query "IdentityProvider.ProviderDetails.$1" --output text | tr -d '\n'; }

p /bgucats/telegram/bot-token      | ghx secret set TELEGRAM_BOT_TOKEN      --env production -R $R
p /bgucats/telegram/webhook-secret | ghx secret set TELEGRAM_WEBHOOK_SECRET --env production -R $R
p /bgucats/submitter-hash-salt     | ghx secret set SUBMITTER_HASH_SALT     --env production -R $R
idp client_id                      | ghx secret set GOOGLE_CLIENT_ID        --env production -R $R
idp client_secret                  | ghx secret set GOOGLE_CLIENT_SECRET    --env production -R $R
aws dynamodb query --profile bgucats-admin --table-name bgucats-data --index-name GSI2 \
  --key-condition-expression 'GSI2PK = :a' --filter-expression 'addedBy = :t' \
  --expression-attribute-values '{":a":{"S":"ENTITY#ADMIN"},":t":{"S":"terraform"}}' \
  --query 'Items[0].email.S' --output text | tr -d '\n' \
                                   | ghx secret set BOOTSTRAP_ADMIN_EMAIL   --env production -R $R
ghx secret list --env production -R $R     # six names, no values
```

The last one reads the email from the allowlist row Terraform owns
(`addedBy = terraform`). The `tr -d '\n'` matters: a trailing newline would
be a different secret, and the first plan would show the SSM parameter
changing (step 5 catches that). The WhatsApp values are **not** secrets
here: Terraform ignores them, and `make whatsapp-secrets` writes them.

### 3c. Ruleset on `main`

*Settings* → *Rules* → *Rulesets* → **New ruleset** → *New branch ruleset*:

- Name `main`, Enforcement status **Active**.
- *Bypass list*: **empty**. That is what "applies to admins too" means for
  rulesets.
- *Target branches* → *Add target* → **Include default branch**.
- Rules:
  - **Restrict deletions** ✓
  - **Block force pushes** ✓
  - **Require a pull request before merging** ✓. Required approvals **0**:
    the PRs are opened under your account, and GitHub never lets an author
    approve their own PR. The rule still forces every change through a PR
    and its checks. Allowed merge methods: Merge, Squash.
  - **Require status checks to pass** ✓ → *Add checks* → `python` and
    `terraform` (source *GitHub Actions*). They appear in the picker once
    they have run on a PR, and both have.
- **Create**.

**If skipped:** without 3a, the deploy role's trust is only as strong as
"nobody writes a workflow that says `environment: production`" (see
above). Without 3b, step 5's runs fail at the plan with "No value for
required variable". Without 3c, anyone or anything with push access can
push to `main`, and that deploys.

---

## 4. Apply `infra/bootstrap` with SSO admin, from PR 2's branch

This creates the deploy role and the boundary, and gives the CI role the
reads it has been missing.

```bash
cd /workspaces/BGUcats
git fetch origin && git checkout deploy-oidc && git pull --ff-only
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY        # this shell only
aws sso login --sso-session bgucats --use-device-code
export AWS_PROFILE=bgucats-admin
aws sts get-caller-identity                           # must be AWSReservedSSO_AdministratorAccess_...
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap plan -out=bootstrap.tfplan
```

**The plan must say `Plan: 10 to import, 7 to add, 1 to change, 0 to destroy.`**
(the run on 2026-10-29 said exactly that):

- **import (10):** `aws_s3_bucket.tfstate`, its `_versioning`,
  `_server_side_encryption_configuration` and `_public_access_block`,
  `aws_dynamodb_table.tfstate_lock`,
  `aws_iam_openid_connect_provider.github_actions`,
  `aws_iam_role.github_actions_ci`, and its policies `_kms_list` and
  `_state_access`. Imports only, with no attribute changes.
- **create (7):** `aws_iam_policy.lambda_boundary`,
  `aws_iam_role.github_actions_deploy`, and its five
  `aws_iam_role_policy.github_actions_deploy_*` (state, storage, compute,
  edge, guards).
- **update in place (1):** `aws_iam_role_policy.github_actions_ci_plan_read`,
  which is also imported. Its new statements: `DescribeAppBuckets`,
  `ReadPublishedObjects`, and the extra `cognito-idp` reads.

**Stop and do not apply if you see any of these:**

- anything to **destroy**, or `-/+` / `must be replaced`, above all on
  `aws_s3_bucket.tfstate` or `aws_dynamodb_table.tfstate_lock`. That would
  lose infra/main's state.
- a change to `aws_iam_openid_connect_provider.github_actions` (its
  thumbprints) or to the CI role's `assume_role_policy`.
- `will be created` for any resource in the import list. That means an
  import did not match, and the apply would fail with "already exists".

If you still have the original bootstrap `terraform.tfstate` from the first
apply, put it in `infra/bootstrap/` first. The plan then shows `0 to
import`, with the same 7 and 1.

Then:

```bash
terraform -chdir=infra/bootstrap apply bootstrap.tfplan
terraform -chdir=infra/bootstrap output      # github_actions_deploy_role_arn, lambda_permissions_boundary_arn
# Keep a copy of the new state where the next machine can find it (the
# bucket is versioned; nothing reads this key automatically):
aws s3 cp infra/bootstrap/terraform.tfstate s3://bgucats-tfstate-851725214678/bootstrap/terraform.tfstate
rm infra/bootstrap/bootstrap.tfplan
```

Finally, on PR 2, **re-run the failed `terraform` check** (*Checks* →
*Re-run failed jobs*). It must now pass. Its plan shows: 6
`aws_iam_role.*` gaining `permissions_boundary`; 6 `aws_lambda_function.*`
with a new `source_code_hash`, explained in step 5; and, from CI's
placeholder secrets only, the three `aws_ssm_parameter` values and
`aws_cognito_identity_provider.google`.

**If skipped:** PR 2 cannot pass its required `terraform` check, and once
merged, every deploy fails at *Configure AWS credentials* (no such role).
Production is untouched either way. **If done before step 3a:** see 3a.
**Applying with the old key** works, but undoes the point; use SSO.

---

## 5. Merge PR 2, check the OIDC claims, plan only, then turn on applies

1. Merge **PR 2 "Deploy from main via OIDC"** (merge commit).
   The push to `main` starts **Deploy** in plan-only mode
   (`PLAN_ONLY_ON_PUSH: "true"`). It cannot apply anything yet.
2. **Check the `sub` claim.** *Actions* → **OIDC claims (debug)** → *Run
   workflow* (branch `main`), and approve it if you set a reviewer. The log
   shows:

   ```json
   { "sub": "repo:sasha720709@254865293/BGUcats@1339652949:environment:production", ... }
   ```

   That example is the expected shape, not a copy of real output. The
   trust policy in `infra/bootstrap/deploy_role.tf` accepts
   `repo:sasha720709@*/BGUcats@*:environment:production`.
   - **Matches:** go on.
   - **Differs** (for example `repo:sasha720709/BGUcats:environment:production`,
     without the IDs): put the printed `sub` in the `values` of the `sub`
     condition in `deploy_role.tf`, exactly, or with `*` only in place of
     the numeric IDs. Then repeat step 4 from a branch with that change
     (the plan shows one in-place update of
     `aws_iam_role.github_actions_deploy`), and merge that branch as a PR.
     **Never** widen it to `repo:sasha720709@*/BGUcats@*:*`: that also
     matches every PR run.
   - Then delete `.github/workflows/oidc-claims-debug.yml` in a small PR.
3. **Plan against live state.** *Actions* → **Deploy** → *Run workflow*,
   `plan_only` ticked (the default). Expected, and nothing else:
   - `Plan: 0 to add, 12 to change, 0 to destroy.`
   - 6 × `aws_iam_role.*` → `+ permissions_boundary = "arn:aws:iam::851725214678:policy/bgucats-lambda-permissions-boundary"`.
     This is new in PR 2.
   - 6 × `aws_lambda_function.*` → `~ source_code_hash`, `~ last_modified`.
     This happens once. The live zips were built with timestamped `.pyc`
     files. The deployed **source** was compared file by file with `main`
     on 2026-10-29 and is identical. From now on, builds are reproducible.
   - Job summary: `Landing page changes: false`.

   What a different plan means:
   - `aws_ssm_parameter.*` or `aws_cognito_identity_provider.google`
     changing: an environment secret differs from the live value, most
     likely a trailing newline. Set it again (3b) and re-run. Do **not**
     apply over it: the bot or Google sign-in would break.
   - `AccessDenied` / `not authorized to perform: X`: the deploy role is
     missing a read. Add `X` to the right statement in
     `infra/bootstrap/deploy_role.tf`, and apply bootstrap as in step 4.
   - Anything to destroy or replace: stop, and find out why before going on.
4. **Turn on applies:** a PR that changes `.github/workflows/deploy.yml`
   in two places:

   ```diff
   -        default: true
   +        default: false
   ...
   -  PLAN_ONLY_ON_PUSH: "true"
   +  PLAN_ONLY_ON_PUSH: "false"
   ```

   Merging it is the **first real deploy**. It applies the 12 changes above.
5. **Check it**, with `docs/deploy.md` → "Post-deploy checks". After this
   apply, two checks matter most, because they exercise the new boundary:
   - **Telegram:** send the bot a photo; "Got it!" back. Then, with
     `--profile bgucats-readonly`, confirm a fresh log stream:
     `aws logs describe-log-streams --log-group-name /aws/lambda/bgucats-ingest --order-by LastEventTime --descending --max-items 1`.
   - **Admin app:** open the Queue (photos load: presigned GETs), label a
     session, reject one photo (S3 version delete).
   - If a Lambda logs `AccessDenied`, the boundary lacks that action. The
     fast fix is widening `infra/bootstrap/lambda_boundary.tf` and applying
     bootstrap (step 4's commands), with no deploy needed. **A `git revert`
     does not help here.** Removing a boundary needs
     `iam:DeleteRolePermissionsBoundary`, which the deploy role is denied
     on purpose.
6. **Prove the builds are reproducible:** run Deploy with `plan_only` once
   more. Expected: `No changes. Your infrastructure matches the
   configuration.`

**If out of order:** running Deploy before step 3b fails on missing
variables. Before step 4, it fails on the role. Flipping to apply before
a plan-only run has matched expectations means applying a plan nobody has
read.

---

## 6. Remove the keys

Only after step 5's real deploy has succeeded and you have used
`--profile bgucats-admin` at least once.

### 6a. GitHub

- Repo → *Settings* → *Secrets and variables* → **Codespaces** → delete
  `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` (both are there, checked
  2026-10-29). `TELEGRAM_BOT_TOKEN` is there too, and every codespace and
  Claude session can read it. It now lives in SSM and in the `production`
  environment, so delete it unless something in the codespace needs it.
- Repo → *Settings* → *Secrets and variables* → **Actions** → *Repository
  secrets*: delete any `AWS_*` there. This could not be listed from the
  codespace.
- <https://github.com/settings/codespaces> → *Secrets*: delete any `AWS_*`
  that has access to `BGUcats`.
- Stop and start the codespace (`gh codespace stop -c <name>`, then open it
  again). Then `env | grep '^AWS_ACCESS'` prints nothing, and
  `postCreate.sh` says "No AWS keys" after a rebuild.

### 6b. IAM: deactivate, watch, delete

`sasha-bgucats-admin` has **two** active keys:

| Key (last 4) | Created | Last used (as of 2026-10-29) | Where it is |
|---|---|---|---|
| `…F4MF` | 2026-08-22 | 2026-10-29, this codespace | the Codespaces secret above |
| `…IITS` | 2026-10-28 | 2026-10-28 18:11 UTC: Terraform 1.15.9 and boto3, from 160.79.106.x, bgucats Lambdas only | unknown: probably a Claude cloud session's environment, or your own machine |

1. As SSO admin, console → *IAM* → *Users* → `sasha-bgucats-admin` →
   *Security credentials* → *Access keys* → for each key: *Actions* →
   **Deactivate**. Deactivating can be undone; deleting cannot.
2. Wait 1–2 days. Look at each key's *Last used* column, and at
   *CloudTrail* → *Event history* → filter *AWS access key* = each key ID.
   A deactivated key that something still tries shows up as failed
   (`InvalidClientTokenId`) calls in that client's own logs, not in
   CloudTrail. So if anything you run broke, that is where to look.
3. Nothing broke → *Actions* → **Delete** each key.

### 6c. The user itself

It has a console password, an MFA device (`arn:aws:iam::851725214678:mfa/iphone`)
and membership of `admins` (AdministratorAccess). With Identity Center
working, and the root user as the emergency door, delete it: *IAM* →
*Users* → `sasha-bgucats-admin` → **Delete**. The console removes the
login profile, MFA, keys and group membership with it. The cautious
alternative is to remove it from `admins` first and delete it a week
later.

### 6d. schedule-ai-app

What could be checked from here, read-only:

- It has its **own** IAM user, `schedule-ai-terraform` (key
  `…QFGB`, last used 2026-08-14), with its own policies.
- Its `CLAUDE.md` says its AWS credentials are **repo-level** Codespaces
  secrets on `schedule-ai-app`, not account-level ones.
- The two bgucats keys' recent CloudTrail activity touched only bgucats
  resources.

So it very likely does not use `sasha-bgucats-admin`. Confirm before 6b's
delete: open a `schedule-ai-app` codespace and run
`aws sts get-caller-identity`. It should print `user/schedule-ai-terraform`.
If it prints `sasha-bgucats-admin`, give it its own credentials first.
Separately, schedule-ai-app is still on long-lived keys itself, and has a
committed `terraform/app/terraform.tfvars`. The same OIDC treatment would
suit it later. Creating the organization in step 1 changes nothing for it: it stays in the same account.

**If done early:** before step 1, no admin access remains except root.
Before step 5 has applied once, nothing proves the pipeline can deploy, and
fixing it needs admin access (SSO, if step 1 is done).

---

## 7. The organization

Done in step 1: `851725214678` is the management account of a new
organization, with no members yet. Two things it makes possible later:

- **More accounts without signups:** *AWS Organizations* → *Add an AWS
  account* → *Create an AWS account* (a name and a new email; a Gmail `+`
  alias works). A staging environment in its own account is the main
  reason you might.
- **Guardrails on those accounts:** a service control policy that denies
  `iam:CreateUser` and `iam:CreateAccessKey` on member accounts, so
  long-lived keys cannot come back there. As said in step 1, SCPs never
  apply to this account itself.

---

## Known gap: the CI role can read production secrets

Not new, and not fixed by these PRs, but you should know. CI runs
`terraform plan` on every PR, and a PR runs **its own** copy of `ci.yml`.
The plan needs the state file, and Terraform state holds every secret in
clear text: the Telegram token, the webhook secret, the salt, and the
Google client secret. So anyone who can push a branch to this repo can
write a workflow that reads them through the CI role. That includes a
Claude Code session with your GitHub token. It cannot change anything in
AWS, but it can read those values.

Ways to close it, in order of effort:

1. Make the secrets *write-only* in Terraform (`value_wo` on
   `aws_ssm_parameter`, Terraform ≥ 1.11), so they never enter state. The
   Google client secret would need the same treatment, or to be set
   outside Terraform the way the WhatsApp secrets already are.
2. Until then, keep push access to the repo to yourself, and treat a
   Claude session's PR that edits `.github/workflows/` as something to read
   before its checks run. GitHub runs them on push, so this rule is about
   which sessions you give the token to.

---

## How you work from now on

- **Change anything:** a branch (yours or a Claude session's) → PR → CI
  runs ruff, pytest and `terraform plan` → read the plan → merge. The
  merge deploys. Nobody runs `terraform apply` on `infra/main` again.
- **Roll back:** `git revert -m 1 <merge commit>` on a branch → PR → merge.
  Data written in the meantime stays (`docs/deploy.md` → Rollback).
  Previous production states are tagged `rollback/*`. A boundary problem
  is fixed forward in bootstrap (step 5.5).
- **You still need SSO admin** (`--profile bgucats-admin`, 1-hour
  sessions) for exactly these jobs, because each one either can't run in
  the pipeline or must not:
  - `infra/bootstrap`: it creates the roles the pipeline runs as. That
    includes widening the boundary, or the deploy role's permissions, for
    a new kind of resource. Apply it **before** the PR that needs it.
  - `make model-publish`: needs torch, and is rare.
  - `make whatsapp-secrets`, `make admin-add`: direct writes to SSM and
    the table.
  - Break-glass, if the pipeline itself is broken. Fix it with a PR
    whenever you can.
- **Everything else read-only** (logs, items, `make tf-plan`) uses
  `--profile bgucats-readonly`, which is also the only profile a Claude
  session should ever be handed.
