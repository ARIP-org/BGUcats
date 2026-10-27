# infra/

Two Terraform root modules:

- **`bootstrap/`** — the state backend (S3 bucket + DynamoDB lock table) and
  the GitHub Actions OIDC role. Uses local state, since it creates the
  backend it would otherwise depend on. Applied once, by hand:

  ```bash
  terraform -chdir=infra/bootstrap init
  terraform -chdir=infra/bootstrap apply
  ```

  Not touched by CI after that beyond `fmt`/`validate`.

- **`main/`** — the actual application resources (phase 1: S3 bucket,
  DynamoDB table, Lambdas, API Gateway, SSM params). Uses the S3 backend
  `bootstrap/` created. This is what CI runs `plan` against on every PR.

## Google sign-in

The admin labeling tool has no passwords. Cognito federates to Google, and a
DynamoDB allowlist decides whose Google account is allowed to exist at all.
Setting that up needs one artifact from outside AWS: an OAuth 2.0 client.

The redirect URI Google needs is knowable before the first apply, because we
choose the Cognito domain prefix ourselves (`var.cognito_domain_prefix`):

```
https://bgucats-admin.auth.us-east-1.amazoncognito.com/oauth2/idpresponse
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
   `google_client_id` / `google_client_secret`, then `make tf-apply`.

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
from Meta, so after `make tf-apply`:

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

The CI role's read access to `/bgucats/whatsapp/*` is in
`bootstrap/github_oidc.tf` and needs a `terraform apply` of `bootstrap/`
from the machine that holds its local state.

## Admins

`bootstrap_admin_email` seeds the first row so the tool can be opened at all;
Terraform owns that one row and will restore it if it is ever deleted, so you
cannot lock yourself out. Everyone else is added either in the tool's
**Admins** tab or with:

```bash
make admin-add EMAIL=someone@post.bgu.ac.il
```

Access is by explicit allowlist, not by email domain. "Anyone with a
@post.bgu.ac.il address" would be every student at the university.

## Naming and tagging

Every resource name is prefixed `bgucats-`. This AWS account also hosts an
unrelated project (`schedule-ai-app`) — the prefix and the `Project =
"bgucats"` default tag (set once, in each root's provider block) are what
keep the two apart for both cost attribution and blast radius.

## IAM: incremental, not upfront

There is no single broad "bgucats-deploy" policy. Permissions are added
resource-by-resource, in the same commit that adds the Terraform resource
needing them:

- **Local `terraform apply`** runs under the developer's own AWS admin user.
  Revisit this once the resource surface is stable enough to make scoping a
  dedicated deploy role cheap.
- **The GitHub Actions CI role** (`bgucats-github-actions-ci`, defined in
  `bootstrap/github_oidc.tf`) starts with exactly the permissions its one
  job (`terraform plan` against `infra/main`) needs: read the state object,
  take/release the DynamoDB lock. When CI takes on a new job against a new
  resource (e.g. an apply-on-merge step for a specific Lambda), extend this
  role's policy in that same commit — never ahead of time for resources
  that don't exist yet.
- **Lambda execution roles**, once `infra/main` has Lambdas, get exactly the
  actions/resource ARNs that function needs (e.g. `s3:PutObject` on the one
  bucket, `dynamodb:PutItem` on the one table) — no wildcards.
