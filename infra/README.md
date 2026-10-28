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
