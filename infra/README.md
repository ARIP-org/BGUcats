# infra/

Three Terraform root modules, applied by different hands.

- **`org/`**: the organization's guardrails, in the management account
  (`851725214678`), acting on the member accounts from outside: the service
  control policies (stay in the organization, `us-east-1` only, **only the
  services this project uses**), a budget per member account whose actions
  attach a freezing policy at $20 and a stopping one at $40, and cost
  anomaly emails from $5. Nothing inside a member account can change them.
  State in `s3://bgucats-org-tfstate-851725214678/`. **Applied from an SSO
  session on the management account**, from a checkout of the branch that
  changes it, never by CI:

  ```bash
  aws sso login --profile mgmt-admin --use-device-code
  infra/scripts/org-apply.sh --plan     # look only; mgmt-ro is enough
  infra/scripts/org-apply.sh            # the same plan, applied after "yes"
  ```

  A service the project starts to use must be added to `allowed_actions`
  in `org/scp.tf` and applied **before** the PR that uses it can deploy.
  Runbook, proofs and the way back: `docs/MANUAL_STEPS.md`, step 13.

  The project's domain name is also the management account's, and is not
  Terraform: `infra/scripts/domain.sh` checks a name, buys it (a price
  ceiling, then "yes") and shows its state. Bought there so that
  `route53domains` never has to be allowed in a member account, and so
  the purchase cannot trip a member account's budget. Step by step:
  `docs/MANUAL_STEPS.md`, step 16.

- **`bootstrap/`**: the state backend (S3 bucket + DynamoDB lock table), the
  GitHub Actions OIDC provider and its two roles, the permissions boundary
  for every role in `main/`, and the account's monthly cost alert. Local state, since it creates the
  backend it would otherwise depend on. **Applied only by the owner**, with an
  IAM Identity Center admin session, from a checkout of the branch that
  changes it:

  ```bash
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
  aws sso login --profile bgucats-prod-admin --use-device-code \
    && infra/scripts/bootstrap-apply.sh; aws sso logout
  ```

  Before it plans, the script runs `infra/bootstrap/tests` (also run by
  CI): the roles' policies against IAM's size limits, and the deploy
  role's guards, with a mocked provider and no AWS call.

  Once per account: production with `bgucats-prod-admin` (the default),
  staging with `AWS_PROFILE=bgucats-staging-admin`. The profile sets
  `var.environment`, the GitHub environment the account's deploy role
  trusts. `bootstrap-apply.sh` checks the account, uses the newer of the
  local state and its copy in the state bucket, keeps the budget alerts'
  address from that state (`TF_VAR_budget_alert_email` overrides it),
  refuses any destroy or replace, shows the plan and applies it only after
  you type `yes`, then puts the new state back in the bucket. The state is
  local, one file per account (`bootstrap/state/<account>.tfstate`,
  gitignored); the copy in the bucket is how the next machine finds it.
  An account's very first apply is `bootstrap-apply.sh --first`, which
  needs the budget address and refuses anything but creates
  (`docs/MANUAL_STEPS.md`, 12c; production's was done by hand, 6b).

  The deploy role cannot read or write that key (only `main/`). CI only runs `fmt` and
  `validate` on it. Change it **before** the PR that needs it: a new kind
  of resource in `main/` needs the deploy role to be allowed to create it,
  and a Lambda that uses a new AWS service needs the boundary widened.

- **`main/`**: the application (buckets, table, Lambdas, API, CloudFront,
  Cognito, SSM parameters). Uses the S3 backend `bootstrap/` created, named
  per account in `main/backend/prod.hcl` and `main/backend/staging.hcl`
  (`terraform -chdir=infra/main init -backend-config=backend/prod.hcl`,
  or `make tf-init PROFILE=bgucats-prod-ro`; a `bgucats-staging-*` profile
  picks staging). The variable `environment` (`production` or `staging`,
  no default) selects what differs between them, all in `main/variables.tf`:
  the Cognito domain prefix and whether the Telegram bot exists. CI
  runs `plan` on every PR; `.github/workflows/deploy.yml` plans and applies
  it to staging on every push to `main`, and to production on a `v*` tag.
  **No person applies it.** Runbook:
  `docs/deploy.md`.

## Google sign-in

The admin labeling tool has no passwords. Cognito federates to Google, and a
DynamoDB allowlist decides whose Google account is allowed to exist at all.
Setting that up needs one artifact from outside AWS: an OAuth 2.0 client.

The redirect URI Google needs is knowable before the first apply, because we
choose the Cognito domain prefix ourselves (`local.settings` in
`main/variables.tf`; staging's is `bgucats-staging`, with a Google client of
its own):

```
https://bgucats-app.auth.us-east-1.amazoncognito.com/oauth2/idpresponse
```

In the [Google Cloud console](https://console.cloud.google.com/):

1. **Create a project** — top-left project picker → *New project* → name it
   `bgucats`. Nothing is billable; this project exists only to own an OAuth
   client.
2. **APIs & Services → OAuth consent screen.** User type *External*. Fill in
   the app name, your email as support and developer contact, and save. No
   scopes need adding — `openid`, `email` and `profile` are always available.
3. Leave the consent screen in **Testing** and add each admin's Google
   address under *Test users*. In Testing mode only those accounts can
   complete the flow, which is a second lock in front of the allowlist. If
   you would rather not manage that list twice, hit *Publish app* — the
   allowlist still holds, and "unverified app" warnings are irrelevant since
   only openid/email/profile are requested.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID.**
   Application type **Web application**. Leave *Authorized JavaScript
   origins* empty — the browser never talks to Google directly here — and add
   the `.../oauth2/idpresponse` URL above under **Authorized redirect URIs**.
5. Give the client ID and client secret to Cognito with
   `AWS_PROFILE=bgucats-prod-admin infra/scripts/set-secret.sh google-oauth`.
   Not Terraform: Cognito returns the secret on every read, so Terraform
   would keep it in its state (`docs/deploy.md`, "Secrets").

If the redirect URI is wrong, Google fails with `redirect_uri_mismatch`
before Cognito is ever reached — compare it character for character with
`terraform -chdir=infra/main output google_redirect_uri`.

## Where contributors come from

The admin tool's **Stats** tab follows people from wherever they heard
about the project to the photos they send:

1. A tracked link — `https://<site>/?src=<slug>` — lands on the landing
   page, which reports the visit to `POST /landing` (`main/beacon.tf`).
   Only daily totals are stored: no cookies, IPs or user agents.
2. The page rewrites its Telegram buttons to `t.me/bgucatsbot?start=<slug>`,
   counting the press.
3. The bot records the slug on the submitter's profile at `/start`, so
   every photo they send later is attributed to it.

Create a link for each partner in **Stats → + Tracked link** and hand out
the landing-page URL it shows. Their own numbers (ad views, plays,
click-throughs) are typed in under **Partner numbers** and sit on top of
the funnel. The poster's QR carries `?src=poster` (`make poster`).

## Admins

`bootstrap_admin_email` seeds the first row so the tool can be opened at all;
Terraform owns that one row and will restore it if it is ever deleted, so you
cannot lock yourself out. Everyone else is added either in the tool's
**People** tab, as an admin or a collaborator, or with:

```bash
make admin-add PROFILE=bgucats-prod-admin EMAIL=someone@post.bgu.ac.il
```

`make admin-add` writes no role, which means admin. People added in the tab
default to **collaborator** — Capture and browsing the cats; no queue or
labeling, and nothing that deletes, merges, names a cat or manages people. Roles can be changed in the tab; nobody can change their own.

Access is by explicit allowlist, not by email domain. "Anyone with a
@post.bgu.ac.il address" would be every student at the university.

## The app (Capture)

The admin URL runs only as an installed app: opened in a browser tab it shows
an install page (Hebrew, English, Russian, Arabic) explaining the app and how
to install it — Share → **Add to Home Screen** on iOS, the install button or
menu on Android, the address-bar install icon in desktop Chrome or Edge.
`<admin_url>?browser` opens it in a tab anyway, if an installed app ever
cannot sign in. Phones upload photos and
videos straight to the media bucket's `raw/` prefix with presigned POSTs,
which is what the bucket's CORS rule in `s3.tf` is for (one origin, POST
only). Nothing new runs all the time; the cost is the same per-photo
Lambda, S3 and DynamoDB usage the bots already incur.

## Naming and tagging

Every resource name is prefixed `bgucats-`, and every resource carries the
`Project = "bgucats"` default tag (set once, in each root's provider
block). Since 2026-10-30 the project runs in an AWS account of its own,
`sasha-bgucats-prod` (`395591097129`), a member of the organization whose
management account (`851725214678`) has run nothing since the old copy was
decommissioned on 2026-11-07 (`docs/MANUAL_STEPS.md`, step 9). The deploy role's
account-wide scopes rely on that: nothing else may be deployed into this
account.

## IAM: three kinds of role, no keys

No IAM user or access key is involved in building or deploying this
project. Every credential below is short-lived and assumed for one job.

| Role | Who assumes it | What it can do | Defined in |
|---|---|---|---|
| `bgucats-github-actions-ci` | `ci.yml`, on every PR and push of this repo | read: the state, and every resource `plan` refreshes | `bootstrap/github_oidc.tf` |
| `bgucats-github-actions-deploy` | `deploy.yml`, only in the `production` environment | plan and apply `main/` | `bootstrap/deploy_role.tf` |
| `bgucats-github-actions-smoke` (staging account only) | `deploy.yml`, in the `staging` environment, after an apply | invoke the admin Lambda, nothing else: the smoke test | `bootstrap/smoke_role.tf` |
| `bgucats-*-lambda` (six) | each Lambda | its own function's needs, capped by the boundary | `main/*.tf`, `bootstrap/lambda_boundary.tf` |

**CI (plan only).** Trusts any job of `ARIP-org/BGUcats` (named
`sasha720709/BGUcats` until 2026-11-07, `docs/MANUAL_STEPS.md` step 11): a
PR from a branch needs a real plan too.
It reads the lock table but never takes the lock (`ci.yml` plans with
`-lock=false`). Read-only, scoped to our resource names, or
to our IDs where a service has no names in its ARNs. Read-only still means
it can read the state, and a PR runs its own `ci.yml`, so whoever can push
a branch can read whatever the state holds. That is why no secret value is
managed by Terraform (`docs/deploy.md`, "Secrets"); see "Known gap" in
`docs/MANUAL_STEPS.md` for what is left.

**Deploy (plan and apply).** Trusts only a `sub` ending in
`:environment:production`. GitHub only lets `main` deploy to that
environment, so a PR run can never assume it. Its permissions are derived
from the resource types in `main/*.tf`, scoped to `bgucats-*` names, or to
the account where AWS assigns IDs (API Gateway, CloudFront, Cognito: see
`bootstrap/infra_main_names.tf`). It can create everything `main/`
declares, so it can build an empty account. It cannot:

- delete a table, a bucket, the user pool or a distribution, or write or
  delete anything in the media bucket (explicit denies). Those are owner
  decisions;
- read the dataset (its only item access is `ADMIN#` keys, for the
  bootstrap admin row) or write the published model under `model/`;
- change its own role, the CI role, the boundary or the OIDC provider
  (explicit denies);
- create or edit any role unless that role carries the boundary.

**Lambda roles and the boundary.** Each Lambda keeps its own role with
exactly the actions and ARNs it needs, extended in the same commit as the
code that needs them, never ahead of time. Every role also carries
`bgucats-lambda-permissions-boundary`: the union of what the Lambdas use
(their log groups, the media bucket, the data table, `/bgucats/*`
parameters). The deploy role can only create or edit a role that has it.
That is what keeps "the deploy role can write IAM" from meaning "the deploy
role is an administrator": a role it writes can never do more than the
boundary allows.

**Changing permissions.** A new resource type in `main/`, or a Lambda that
needs a new service, is two steps: a `bootstrap/` change applied by the
owner, then the PR that uses it. The other order fails the deploy with
`AccessDenied`, which is the guard working.

**People.** IAM Identity Center, not IAM users: a `ReadOnlyAccess`
permission set for debugging (`docs/codespaces.md`) and an
`AdministratorAccess` one, with short sessions, for `bootstrap/`, the model
publish and break-glass only. Setup: `docs/MANUAL_STEPS.md`.
