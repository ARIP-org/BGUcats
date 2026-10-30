# infra/

Two Terraform root modules, applied by different hands, and `org/`: the
service control policy for the organization's member accounts, applied by
the owner from the management account (`docs/MANUAL_STEPS.md`, step 10).

- **`bootstrap/`**: the state backend (S3 bucket + DynamoDB lock table), the
  GitHub Actions OIDC provider and its two roles, and the permissions
  boundary for every role in `main/`. Local state, since it creates the
  backend it would otherwise depend on. **Applied only by the owner**, with an
  IAM Identity Center admin session, from a checkout of the branch that
  changes it:

  ```bash
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
  aws sso login --profile bgucats-prod-admin
  export AWS_PROFILE=bgucats-prod-admin
  infra/scripts/aws-guard.sh                # must say account 395591097129
  aws s3 cp s3://bgucats-tfstate-395591097129/bootstrap/terraform.tfstate infra/bootstrap/
  terraform -chdir=infra/bootstrap init
  terraform -chdir=infra/bootstrap plan -out=bootstrap.tfplan   # read it: no destroy, no replace
  terraform -chdir=infra/bootstrap apply bootstrap.tfplan
  aws s3 cp infra/bootstrap/terraform.tfstate s3://bgucats-tfstate-395591097129/bootstrap/terraform.tfstate
  rm infra/bootstrap/bootstrap.tfplan
  ```

  The state is local (`*.tfstate` is gitignored). The copy in the state
  bucket is how the next machine finds it: fetch it before every plan, put
  it back after every apply. The very first apply in an account has nothing
  to fetch; that one is `docs/MANUAL_STEPS.md`, step 6.

  The deploy role cannot read or write that key (only `main/`). CI only runs `fmt` and
  `validate` on it. Change it **before** the PR that needs it: a new kind
  of resource in `main/` needs the deploy role to be allowed to create it,
  and a Lambda that uses a new AWS service needs the boundary widened.

- **`main/`**: the application (buckets, table, Lambdas, API, CloudFront,
  Cognito, SSM parameters). Uses the S3 backend `bootstrap/` created, named
  per account in `main/backend/prod.hcl`
  (`terraform -chdir=infra/main init -backend-config=backend/prod.hcl`,
  or `make tf-init PROFILE=bgucats-prod-ro`). CI
  runs `plan` on every PR; `.github/workflows/deploy.yml` plans and applies
  it on every push to `main`. **No person applies it.** Runbook:
  `docs/deploy.md`.

## Google sign-in

The admin labeling tool has no passwords. Cognito federates to Google, and a
DynamoDB allowlist decides whose Google account is allowed to exist at all.
Setting that up needs one artifact from outside AWS: an OAuth 2.0 client.

The redirect URI Google needs is knowable before the first apply, because we
choose the Cognito domain prefix ourselves (`var.cognito_domain_prefix`):

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
5. Copy the client ID and client secret into `terraform.tfvars` as
   the `production` environment secrets `GOOGLE_CLIENT_ID` /
   `GOOGLE_CLIENT_SECRET` (`docs/MANUAL_STEPS.md`), and run Deploy.

If the redirect URI is wrong, Google fails with `redirect_uri_mismatch`
before Cognito is ever reached — compare it character for character with
`terraform -chdir=infra/main output google_redirect_uri`.

## WhatsApp

The WhatsApp bot is a second Lambda (`bgucats-whatsapp`, in
`main/whatsapp.tf`) on the same ingest code, behind the same API at
`/webhook/whatsapp`. Sessions, photos and locations land in the same table
and the same labeling queue as Telegram's; records carry `channel =
"whatsapp"`.

Terraform creates its three SSM parameters with the value `unset`, and the
Lambda refuses every request (503) until they are real. The values come
from Meta, so once the deploy has created them:

1. **[developers.facebook.com](https://developers.facebook.com/apps)** →
   *Create app* → use case *Other* → type *Business*. Add the **WhatsApp**
   product. Meta creates a test business account with a **test phone
   number**, free, that can message up to five numbers you verify under
   *WhatsApp → API Setup → To*.
2. **Permanent token.** The token on the API Setup page expires in 24h.
   In [Business settings](https://business.facebook.com/settings) →
   *Users → System users* → add one (Admin) → *Assign assets* → this app,
   full control → *Generate token* for this app with
   `whatsapp_business_messaging` and `whatsapp_business_management`,
   expiry *Never*.
3. **App secret.** App dashboard → *App settings → Basic* → *App secret*.
4. `make whatsapp-secrets` — paste the two values; it generates the
   verify token, stores all three, and prints the callback URL and verify
   token.
5. Dashboard → *WhatsApp → Configuration → Webhook → Edit*: paste both,
   *Verify and save*, then **subscribe to `messages`**.

Message the test number from one of the verified phones: "hi" should get
the introduction back. To open it to everyone, add a real phone number
under *WhatsApp → API Setup* (it must not already be registered in the
WhatsApp app), get its display name approved, and switch the app to *Live*
— which requires a privacy-policy URL. Conversations the user starts are
free on the Cloud API; this bot never starts one.

`make whatsapp-secrets` writes to SSM, so it is an owner step with an SSO
admin session (`make whatsapp-secrets PROFILE=bgucats-prod-admin`). Terraform ignores these
values, so a deploy never overwrites them.

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
block). Since 2026-10 the project has an AWS account of its own,
`sasha-bgucats-prod` (`395591097129`), a member of the organization whose
management account (`851725214678`) runs nothing. The deploy role's
account-wide scopes rely on that: nothing else may be deployed into this
account.

## IAM: three kinds of role, no keys

No IAM user or access key is involved in building or deploying this
project. Every credential below is short-lived and assumed for one job.

| Role | Who assumes it | What it can do | Defined in |
|---|---|---|---|
| `bgucats-github-actions-ci` | `ci.yml`, on every PR and push of this repo | read: the state, and every resource `plan` refreshes | `bootstrap/github_oidc.tf` |
| `bgucats-github-actions-deploy` | `deploy.yml`, only in the `production` environment | plan and apply `main/` | `bootstrap/deploy_role.tf` |
| `bgucats-*-lambda` (six) | each Lambda | its own function's needs, capped by the boundary | `main/*.tf`, `bootstrap/lambda_boundary.tf` |

**CI (plan only).** Trusts any job of `sasha720709/BGUcats`: a PR from a
branch needs a real plan too. Read-only, scoped to our resource names, or
to our IDs where a service has no names in its ARNs. Read-only still means
it can read the state, and the state holds the secret values in clear
text. A PR runs its own `ci.yml`, so whoever can push a branch can reach
them. See "Known gap" in `docs/MANUAL_STEPS.md`.

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
