# Lets GitHub Actions authenticate to AWS via short-lived OIDC-issued
# credentials instead of long-lived access keys stored as repo secrets.
#
# AWS validates GitHub's OIDC tokens against its own trusted CA bundle, not
# this field, but the API still requires a syntactically valid thumbprint.
# token.actions.githubusercontent.com now serves a Let's Encrypt chain
# (leaf -> R-series intermediate -> ISRG Root YR -> ISRG Root X1), so the
# once-standard DigiCert thumbprints for this provider are stale. These are
# the actual SHA-1 fingerprints of the top-of-chain cert served by GitHub
# and of ISRG Root X1 itself (the stable, self-signed root), captured via:
#   openssl s_client -connect token.actions.githubusercontent.com:443 -showcerts
resource "aws_iam_openid_connect_provider" "github_actions" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  thumbprint_list = [
    "cabd2a79a1076a31f21d253635cb039d4329a5e8", # ISRG Root X1 (self-signed root)
    "ab9d0263244dd0326eb67015705a667e79cfe998", # ISRG Root YR (top cert served in chain)
  ]
}

data "aws_iam_policy_document" "github_actions_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # AWS requires every GitHub-OIDC trust policy to constrain `sub` (or
    # `job_workflow_ref`) to something other than a bare wildcard — it
    # rejects an UpdateAssumeRolePolicy that omits it. This environment's
    # actual `sub` embeds numeric owner/repo IDs
    # ("repo:sasha720709@<id>/BGUcats@<id>:ref:refs/heads/main") rather than
    # the plain "repo:owner/name:..." documented for github.com, so the
    # wildcards sit around those ID segments. `repository` (exact "owner/repo")
    # is the claim that actually does the scoping precisely.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:sasha720709@*/BGUcats@*:*"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:repository"
      values   = ["sasha720709/BGUcats"]
    }
  }
}

resource "aws_iam_role" "github_actions_ci" {
  name               = "bgucats-github-actions-ci"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust.json
}

# infra/main's `terraform plan` (which CI runs on every PR) evaluates the
# aws_kms_alias data source regardless of what's already applied, to
# resolve the SSM SecureString decryption key. That data source resolves
# the alias via kms:ListAliases (no resource-level scoping — one of the
# few KMS actions AWS requires Resource "*" for) and then reads the
# resolved key's metadata via kms:DescribeKey, scoped to that one key.
# Neither exposes key material or a decrypt capability.
data "aws_kms_alias" "ssm" {
  name = "alias/aws/ssm"
}

resource "aws_iam_role_policy" "github_actions_ci_kms_list" {
  name = "bgucats-kms-list-aliases"
  role = aws_iam_role.github_actions_ci.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListKmsAliasesForPlan"
        Effect   = "Allow"
        Action   = "kms:ListAliases"
        Resource = "*"
      },
      {
        Sid      = "DescribeSsmKmsKeyForPlan"
        Effect   = "Allow"
        Action   = "kms:DescribeKey"
        Resource = data.aws_kms_alias.ssm.target_key_arn
      },
    ]
  })
}

# CI's only current job is `terraform plan`, which needs to read the state
# object and take/release the DynamoDB lock — nothing more. Scoped to
# exactly the two resources this same root module creates. Extend this
# policy (never a broad managed policy) in the same commit that gives CI a
# new job against a new resource.
resource "aws_iam_role_policy" "github_actions_ci_state_access" {
  name = "bgucats-tfstate-read"
  role = aws_iam_role.github_actions_ci.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListStateBucket"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.tfstate.arn
      },
      {
        Sid      = "ReadStateObjects"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.tfstate.arn}/*"
      },
      {
        Sid    = "StateLock"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
        ]
        Resource = aws_dynamodb_table.tfstate_lock.arn
      },
    ]
  })
}

# `terraform plan` against infra/main refreshes every resource already
# applied there before it can compute a diff — read-only Describe/Get/List
# calls per resource type, distinct from (and in addition to) the runtime
# permissions those resources' own execution roles carry. Resource names
# are hardcoded because they're names *we* chose (deterministic), unlike
# AWS-assigned IDs (e.g. the API Gateway API ID) which aren't known here —
# infra/bootstrap and infra/main deliberately don't share state, so this
# can't reference infra/main's resources directly.
resource "aws_iam_role_policy" "github_actions_ci_plan_read" {
  name = "bgucats-plan-read-infra-main"
  role = aws_iam_role.github_actions_ci.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DescribeDataTable"
        Effect = "Allow"
        Action = [
          "dynamodb:DescribeTable",
          "dynamodb:DescribeTimeToLive",
          "dynamodb:DescribeContinuousBackups",
          "dynamodb:ListTagsOfResource",
        ]
        Resource = "arn:aws:dynamodb:us-east-1:${data.aws_caller_identity.current.account_id}:table/bgucats-data"
      },
      {
        Sid    = "DescribeMediaBucket"
        Effect = "Allow"
        Action = [
          "s3:GetBucket*",
          "s3:GetEncryptionConfiguration",
          "s3:GetLifecycleConfiguration",
          "s3:GetReplicationConfiguration",
          "s3:GetAccelerateConfiguration",
        ]
        Resource = "arn:aws:s3:::bgucats-media-${data.aws_caller_identity.current.account_id}"
      },
      {
        Sid    = "DescribeIngestLambdaRole"
        Effect = "Allow"
        Action = [
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:ListRoleTags",
        ]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/bgucats-ingest-lambda"
      },
      {
        Sid    = "DescribeIngestLambda"
        Effect = "Allow"
        Action = [
          "lambda:GetFunction",
          "lambda:GetPolicy",
        ]
        Resource = "arn:aws:lambda:us-east-1:${data.aws_caller_identity.current.account_id}:function:bgucats-ingest"
      },
      {
        Sid      = "DescribeApiGateway"
        Effect   = "Allow"
        Action   = "apigateway:GET"
        Resource = "arn:aws:apigateway:us-east-1::/apis/*"
      },
      {
        Sid    = "DescribeSecretsForPlan"
        Effect = "Allow"
        Action = ["ssm:GetParameter", "ssm:ListTagsForResource"]
        Resource = [
          "arn:aws:ssm:us-east-1:${data.aws_caller_identity.current.account_id}:parameter/bgucats/telegram/bot-token",
          "arn:aws:ssm:us-east-1:${data.aws_caller_identity.current.account_id}:parameter/bgucats/telegram/webhook-secret",
          "arn:aws:ssm:us-east-1:${data.aws_caller_identity.current.account_id}:parameter/bgucats/submitter-hash-salt",
        ]
      },
      {
        # DescribeParameters (metadata, not values — tier/type/tags) is
        # one more KMS-ListAliases-shaped action: no resource-level
        # scoping, must be Resource "*".
        Sid      = "DescribeSecretsMetadataForPlan"
        Effect   = "Allow"
        Action   = "ssm:DescribeParameters"
        Resource = "*"
      },
    ]
  })
}

output "github_actions_ci_role_arn" {
  value = aws_iam_role.github_actions_ci.arn
}
