> **Historical.** The runbook for the 2026-10-28 deploy, run by hand. Deploys
> now go through a pull request to `main`: see `docs/deploy.md`.

# Deploying `app-preprod` — the installable app, roles and Capture

A runbook for one deploy: it is written for whoever runs it next, by hand
or with Claude Code in the codespace. Run every step in the codespace, where
`terraform.tfvars` and the AWS credentials already are.

## What is being deployed

`app-preprod` is `admin-labeling-tool` (what production runs today) plus one
commit that turns the labeling tool into an installable app:

- **Roles** on the existing allowlist item: `admin` (everything, as today)
  and `collaborator` (Capture, browse cats, assign queue sessions to cats that
  already exist). An item with no role is an admin, so every current account
  keeps full access. Managed in the **People** tab (was Admins).
- **Capture**: an in-app camera for collaborators. Photos and videos upload
  from the phone straight to `raw/` with presigned POSTs, and go through the
  same process Lambda and queue as bot photos (`channel = "app"`). Location
  is the phone's GPS at the moment of capture, with its accuracy.
- **Installable** (PWA): manifest, icons, and a network-first service worker
  that never touches `/api/` or photos.

The Telegram and WhatsApp bots, the process Lambda, the landing page and the
data model are not changed. Details: "The app" in `CLAUDE.md`.

**Checked before writing this (2026-10-28):** the deployed Lambda code and
web files are byte-identical to `admin-labeling-tool`, so applying this
branch adds only the changes below and rolls nothing back.

## Why in place, not as a second app

A second Lambda and site would still have to read and write the same table
and bucket, because the real cats live there. So it would isolate only the
screens, not the data, which is where the risk is, while doubling the
infrastructure and adding a later cut-over. The change is additive and
backward compatible, and rollback is one apply (below).

## 1. Check out and test

```bash
cd /workspaces/BGUcats
```

```bash
git fetch origin && git checkout app-preprod && git pull
```

```bash
make lint && make test
```

All 279 tests should pass.

## 2. Plan, and read it

```bash
make tf-plan
```

Expected, and nothing else:

| Resource | Change |
|---|---|
| `aws_iam_role_policy.admin_lambda_access` | update in place: adds `s3:PutObject` on `raw/*`, used to sign the phone's uploads |
| `aws_s3_bucket_cors_configuration.media` | **create**: lets the app's own origin POST to the media bucket; nothing readable |
| `aws_s3_object.web["app.js"]`, `["index.html"]`, `["styles.css"]` | update in place |
| `aws_s3_object.web[...]` for `capture.js`, `outbox.js`, `sw.js`, `manifest.webmanifest`, `icon.svg`, `icon-192.png`, `icon-512.png`, `apple-touch-icon.png` | create (8) |
| `aws_lambda_function.admin`, `aws_lambda_function.admin_presignup` | update in place: new code (they share one zip) |

The other Lambdas (ingest, whatsapp, process, beacon) may also show a code
update. That is only a rebuilt zip of identical source; it is harmless.

**Stop if the plan shows anything to destroy or replace**, or any change to
Cognito, SSM parameters, the DynamoDB table, CloudFront, or API Gateway.

## 3. Apply

```bash
make tf-apply
```

## 4. Check the live system

Your email is the bootstrap admin (`bootstrap_admin_email` in
`terraform.tfvars`):

```bash
ME=$(grep bootstrap_admin_email infra/main/terraform.tfvars | cut -d'"' -f2)
```

Ask the deployed API who you are, the way API Gateway would after login. It
should say `"role": "admin"`:

```bash
aws lambda invoke --function-name bgucats-admin --cli-binary-format raw-in-base64-out \
  --payload "{\"requestContext\":{\"http\":{\"method\":\"GET\",\"path\":\"/api/me\"},\"authorizer\":{\"jwt\":{\"claims\":{\"email\":\"$ME\"}}}}}" \
  /tmp/me.json && cat /tmp/me.json
```

The new encounters list. An empty list proves the new query works:

```bash
aws lambda invoke --function-name bgucats-admin --cli-binary-format raw-in-base64-out \
  --payload "{\"requestContext\":{\"http\":{\"method\":\"GET\",\"path\":\"/api/encounters\"},\"authorizer\":{\"jwt\":{\"claims\":{\"email\":\"$ME\"}}}}}" \
  /tmp/enc.json && cat /tmp/enc.json
```

The bucket's CORS rule should name only the admin site:

```bash
aws s3api get-bucket-cors --bucket "$(terraform -chdir=infra/main output -raw media_bucket)"
```

## 5. Try it on a phone

```bash
terraform -chdir=infra/main output -raw admin_url
```

1. Open that URL on your phone and sign in. The Queue, Cats and Stats should
   look as before, and Admins is now **People**.
2. **iPhone:** Share → Add to Home Screen. **Android:** the install prompt.
   Open the installed app and **sign in again inside it**. This is the step
   most worth checking: iOS is sometimes awkward with sign-in inside
   home-screen apps.
3. Capture → Start an encounter. Allow the camera and location, take two
   photos and a short video, then press "Done — next cat". The encounter
   should appear in the Queue, "via the app", with "phone GPS ±N m".
4. In People, add a collaborator. Sign in as them, or ask them to: they
   should see only Capture, Queue and Cats.

## Rollback

```bash
git checkout admin-labeling-tool && make tf-apply
```

That restores the previous API and screens in about two minutes. The CORS
rule and the extra IAM permission are removed with it. Anything collaborators
uploaded stays, as ordinary sessions in the queue.

## Cost

Nothing new runs all the time. Each photo costs the same per-request Lambda,
S3 and DynamoDB amounts the bots already incur: cents per month at this
scale.
