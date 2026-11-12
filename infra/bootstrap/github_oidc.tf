# Lets GitHub Actions authenticate to AWS via short-lived OIDC-issued
# credentials instead of long-lived access keys stored as repo secrets.
#
# Two roles trust this provider: bgucats-github-actions-ci below (plan only,
# any branch or PR of this repo) and bgucats-github-actions-deploy in
# deploy_role.tf (apply, only jobs in this account's environment,
# `production` or `staging`).
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

# The names GitHub may give this repo in a token. The repo moved from the
# owner's account (sasha720709/BGUcats) to the ARIP-org organization on
# 2026-11-07 (docs/MANUAL_STEPS.md, step 11). A transfer changes the
# `repository` and `sub` claims at once, so for a move both names are listed
# here first, and the old one is dropped once a CI run and a deploy have
# used the new one. The numeric repo ID (1339652949) survives a transfer;
# the owner segment is ARIP-org's (353802310).
locals {
  github_repos = ["ARIP-org/BGUcats"]

  # "owner/name" -> "repo:owner@*/name@*", the start of the token's `sub`.
  github_sub_prefixes = [
    for r in local.github_repos : format("repo:%s@*/%s@*", split("/", r)[0], split("/", r)[1])
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
    # ("repo:ARIP-org@<id>/BGUcats@<id>:ref:refs/heads/main") rather than
    # the plain "repo:owner/name:..." documented for github.com, so the
    # wildcards sit around those ID segments. `repository` (exact "owner/repo")
    # is the claim that actually does the scoping precisely.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [for p in local.github_sub_prefixes : "${p}:*"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:repository"
      values   = local.github_repos
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
# object and the lock table — nothing more. It plans with -lock=false
# (ci.yml) because it runs at the same time as Deploy on every merge, so it
# never takes or releases the lock; GetItem stays for the S3 backend's
# state digest, which it reads from the same table. Scoped to
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
        Sid      = "StateLockRead"
        Effect   = "Allow"
        Action   = "dynamodb:GetItem"
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
        Sid    = "DescribeTables"
        Effect = "Allow"
        Action = [
          "dynamodb:DescribeTable",
          "dynamodb:DescribeTimeToLive",
          "dynamodb:DescribeContinuousBackups",
          "dynamodb:ListTagsOfResource",
        ]
        Resource = local.app_table_arns
      },
      {
        # HeadBucket is authorized as s3:ListBucket. Bucket tags are read
        # through S3 Control's ListTagsForResource since provider 6.x.
        Sid    = "DescribeAppBuckets"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucket*",
          "s3:GetEncryptionConfiguration",
          "s3:GetLifecycleConfiguration",
          "s3:GetReplicationConfiguration",
          "s3:GetAccelerateConfiguration",
          "s3:ListTagsForResource",
        ]
        Resource = local.app_bucket_arns
      },
      {
        # The landing page and the admin app are Terraform-managed objects,
        # so plan reads each one back (HeadObject is s3:GetObject). Never the
        # media bucket: those are people's photos, and Terraform owns none.
        Sid    = "ReadPublishedObjects"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectTagging",
        ]
        Resource = local.published_object_arns
      },
      {
        # bgucats-* rather than one entry per function: read-only, still
        # confined to this project's names, and every new Lambda would
        # otherwise break CI until this policy was extended by hand.
        Sid    = "DescribeLambdaRoles"
        Effect = "Allow"
        Action = [
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:ListRoleTags",
        ]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/bgucats-*"
      },
      {
        # The functions, and the mapping that feeds one from the social
        # table's stream.
        Sid    = "DescribeLambdas"
        Effect = "Allow"
        Action = [
          "lambda:GetFunction",
          "lambda:GetPolicy",
          "lambda:ListVersionsByFunction",
          "lambda:GetFunctionCodeSigningConfig",
          "lambda:GetEventSourceMapping",
          "lambda:ListTags",
        ]
        Resource = [
          "arn:aws:lambda:us-east-1:${data.aws_caller_identity.current.account_id}:function:bgucats-*",
          local.event_source_mapping_arns,
        ]
      },
      {
        Sid      = "DescribeApiGateway"
        Effect   = "Allow"
        Action   = "apigateway:GET"
        Resource = "arn:aws:apigateway:us-east-1::/apis/*"
      },
      # No SSM and no Cognito identity provider: the secrets are outside
      # Terraform (infra/main/ssm.tf), so plan never reads them, and this
      # role — which any PR's workflow can drive — must not be able to.
      {
        # Read-only, and the account runs nothing else. ListCachePolicies
        # and DescribeUserPoolDomain have no resource-level scoping at all.
        Sid    = "DescribeCloudFrontAndCognitoForPlan"
        Effect = "Allow"
        Action = [
          "cloudfront:GetDistribution",
          "cloudfront:GetOriginAccessControl",
          "cloudfront:GetCachePolicy",
          "cloudfront:GetOriginRequestPolicy",
          "cloudfront:ListCachePolicies",
          "cloudfront:ListOriginRequestPolicies",
          "cloudfront:ListTagsForResource",
          "cognito-idp:DescribeUserPool",
          "cognito-idp:DescribeUserPoolClient",
          "cognito-idp:DescribeUserPoolDomain",
          "cognito-idp:DescribeManagedLoginBranding",
          "cognito-idp:DescribeManagedLoginBrandingByClient",
          "cognito-idp:GetUserPoolMfaConfig",
          "cognito-idp:ListUserPoolClients",
          "cognito-idp:ListTagsForResource",
        ]
        Resource = "*"
      },
      {
        # alarms.tf. Read-only: the topic's settings, the subscription's
        # (not a resource IAM can name, hence "*"), and the alarms.
        Sid    = "DescribeAlertsForPlan"
        Effect = "Allow"
        Action = [
          "sns:GetTopicAttributes",
          "sns:ListTagsForResource",
          "sns:GetSubscriptionAttributes",
          "cloudwatch:DescribeAlarms",
          "cloudwatch:ListTagsForResource",
        ]
        Resource = "*"
      },
      {
        # The bootstrap admin row is a Terraform-managed table item, so plan
        # has to read it back. Scoped to the one table.
        Sid      = "ReadBootstrapAdminItem"
        Effect   = "Allow"
        Action   = "dynamodb:GetItem"
        Resource = "arn:aws:dynamodb:us-east-1:${data.aws_caller_identity.current.account_id}:table/bgucats-data"
      },
    ]
  })
}

output "github_actions_ci_role_arn" {
  value = aws_iam_role.github_actions_ci.arn
}
