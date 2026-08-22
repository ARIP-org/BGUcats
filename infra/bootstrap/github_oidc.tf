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

    # Scoped to this repo, any branch/PR/ref within it.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:sasha720709/BGUcats:*"]
    }
  }
}

resource "aws_iam_role" "github_actions_ci" {
  name               = "bgucats-github-actions-ci"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust.json
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

output "github_actions_ci_role_arn" {
  value = aws_iam_role.github_actions_ci.arn
}
