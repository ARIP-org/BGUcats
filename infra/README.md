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
