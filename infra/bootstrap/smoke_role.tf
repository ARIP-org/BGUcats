# The role the deploy job's smoke test runs under (scripts/smoke_staging.py,
# .github/workflows/deploy.yml). Staging only: the test puts a made-up photo
# through the app and deletes it again, which production must never see, so
# in the production account this role does not exist.
#
# It can do one thing: invoke the admin Lambda. With that it can call the
# API as any member, because the test hands the Lambda the event API
# Gateway would, with the caller's email already "verified". That is the
# whole of staging's data, which is made up, and nothing else: no table,
# no bucket, no other function, no IAM. The photo itself goes to S3 with
# the presigned upload the API returns, as a phone's does.
#
# Trusted like the deploy role: only a job in the GitHub environment
# `staging`, which GitHub lets only `main` claim.
resource "aws_iam_role" "github_actions_smoke" {
  count = var.environment == "staging" ? 1 : 0

  name                 = "bgucats-github-actions-smoke"
  description          = "Assumed by deploy.yml (environment staging) after an apply, to run the smoke test through the admin Lambda."
  assume_role_policy   = data.aws_iam_policy_document.github_actions_deploy_trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy" "github_actions_smoke" {
  count = var.environment == "staging" ? 1 : 0

  name = "bgucats-smoke-invoke-admin"
  role = aws_iam_role.github_actions_smoke[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "InvokeTheAdminLambdaOnly"
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = "arn:aws:lambda:us-east-1:${local.account_id}:function:bgucats-admin"
    }]
  })
}
