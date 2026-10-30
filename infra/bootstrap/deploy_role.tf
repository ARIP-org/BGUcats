# The role .github/workflows/deploy.yml assumes to plan and apply
# infra/main. It replaces the IAM user with AdministratorAccess that every
# deploy before 2026-10 ran under. Nobody else holds it: no human, no
# codespace, no PR run.
#
# What it may do is derived from the resource types in infra/main/*.tf, and
# scoped to their names (or, where AWS only offers IDs, to the account: see
# infra_main_names.tf). It can create everything infra/main declares, so a
# deploy can build an empty account. Four things it deliberately cannot do:
#   - delete a table, a bucket or the user pool, or anything in the media
#     bucket (explicit denies below). A plan that tries fails at apply.
#     Destroying stored data is an owner decision.
#   - give any role more than the Lambda permissions boundary
#     (lambda_boundary.tf), or touch the GitHub roles, the boundary, or
#     the OIDC provider. That is what stops it from escalating.
#   - read or write the dataset. Its only item access is the bootstrap
#     admin row, and only ADMIN# keys.
#   - write the recognition model under model/, which the owner publishes.

data "aws_iam_policy_document" "github_actions_deploy_trust" {
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

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:repository"
      values   = ["sasha720709/BGUcats"]
    }

    # The difference from the CI role. A job bound to a GitHub environment
    # gets a `sub` ending in ":environment:<name>" instead of the ref or
    # "pull_request", so only jobs in `production` match. GitHub lets only
    # `main` deploy to that environment (its deployment-branch rule), and a
    # PR from a fork or a branch can't claim it. The numeric-ID segments are
    # the same as in the CI role's trust. Proven on 2026-10-30: deploy.yml
    # assumed this role from `production` on its first runs.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:sasha720709@*/BGUcats@*:environment:production"]
    }
  }
}

resource "aws_iam_role" "github_actions_deploy" {
  name                 = "bgucats-github-actions-deploy"
  description          = "Assumed by deploy.yml (environment production) to plan and apply infra/main."
  assume_role_policy   = data.aws_iam_policy_document.github_actions_deploy_trust.json
  max_session_duration = 3600
}

# Terraform state for infra/main only, read and write, plus the lock. Not
# DeleteObject: the bucket is versioned, and the history is the way back if
# an apply ever writes a bad state.
resource "aws_iam_role_policy" "github_actions_deploy_state" {
  name = "bgucats-deploy-tfstate"
  role = aws_iam_role.github_actions_deploy.id

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
        Sid      = "ReadWriteMainState"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${aws_s3_bucket.tfstate.arn}/main/terraform.tfstate"
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

# s3.tf, site.tf, web.tf and dynamodb.tf.
resource "aws_iam_role_policy" "github_actions_deploy_storage" {
  name = "bgucats-deploy-storage"
  role = aws_iam_role.github_actions_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Bucket settings for the three app buckets, listed by name so the
        # state bucket is never inside a wildcard. No DeleteBucket.
        Sid    = "AppBucketSettings"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket",
          "s3:ListBucket",
          "s3:GetBucket*",
          "s3:GetEncryptionConfiguration",
          "s3:GetLifecycleConfiguration",
          "s3:GetReplicationConfiguration",
          "s3:GetAccelerateConfiguration",
          "s3:ListTagsForResource",
          "s3:TagResource",
          "s3:UntagResource",
          "s3:PutBucketTagging",
          "s3:PutBucketVersioning",
          "s3:PutEncryptionConfiguration",
          "s3:PutBucketPublicAccessBlock",
          "s3:PutLifecycleConfiguration",
          "s3:PutBucketCORS",
          "s3:PutBucketNotification",
          "s3:PutBucketPolicy",
          "s3:DeleteBucketPolicy",
        ]
        Resource = local.app_bucket_arns
      },
      {
        # The landing page and the admin app's files. Objects carry the
        # default tags, hence the tagging actions.
        Sid    = "PublishedObjects"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:GetObjectTagging",
          "s3:PutObjectTagging",
        ]
        Resource = local.published_object_arns
      },
      {
        # The table itself. No DeleteTable.
        Sid    = "DataTable"
        Effect = "Allow"
        Action = [
          "dynamodb:CreateTable",
          "dynamodb:UpdateTable",
          "dynamodb:DescribeTable",
          "dynamodb:DescribeTimeToLive",
          "dynamodb:UpdateTimeToLive",
          "dynamodb:DescribeContinuousBackups",
          "dynamodb:UpdateContinuousBackups",
          "dynamodb:ListTagsOfResource",
          "dynamodb:TagResource",
          "dynamodb:UntagResource",
        ]
        Resource = local.data_table_arn
      },
      {
        # aws_dynamodb_table_item.bootstrap_admin, and nothing else in the
        # table: IAM checks the partition key, the same way the beacon
        # Lambda is held to TRAFFIC# keys.
        Sid      = "BootstrapAdminItemOnly"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
        Resource = local.data_table_arn
        Condition = {
          "ForAllValues:StringLike" = {
            "dynamodb:LeadingKeys" = ["ADMIN#*"]
          }
        }
      },
    ]
  })
}

# lambda.tf, process_lambda.tf, admin_api.tf, beacon.tf, api.tf.
resource "aws_iam_role_policy" "github_actions_deploy_compute" {
  name = "bgucats-deploy-compute"
  role = aws_iam_role.github_actions_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Lambdas"
        Effect = "Allow"
        Action = [
          "lambda:CreateFunction",
          "lambda:DeleteFunction",
          "lambda:GetFunction",
          "lambda:GetFunctionConfiguration",
          "lambda:GetFunctionCodeSigningConfig",
          "lambda:ListVersionsByFunction",
          "lambda:UpdateFunctionCode",
          "lambda:UpdateFunctionConfiguration",
          "lambda:GetPolicy",
          "lambda:AddPermission",
          "lambda:RemovePermission",
          "lambda:ListTags",
          "lambda:TagResource",
          "lambda:UntagResource",
        ]
        Resource = "arn:aws:lambda:us-east-1:${local.account_id}:function:bgucats-*"
      },
      {
        Sid    = "ReadLambdaRoles"
        Effect = "Allow"
        Action = [
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:ListInstanceProfilesForRole",
          "iam:ListRoleTags",
        ]
        Resource = "arn:aws:iam::${local.account_id}:role/bgucats-*"
      },
      {
        # The escalation guard: every action that sets what a role may do
        # requires the role to carry the boundary (lambda_boundary.tf), so
        # a role without it can be neither created nor edited.
        Sid    = "WriteLambdaRolesWithinBoundary"
        Effect = "Allow"
        Action = [
          "iam:CreateRole",
          "iam:PutRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:PutRolePermissionsBoundary",
        ]
        Resource = "arn:aws:iam::${local.account_id}:role/bgucats-*"
        Condition = {
          StringEquals = {
            "iam:PermissionsBoundary" = aws_iam_policy.lambda_boundary.arn
          }
        }
      },
      {
        # The one managed policy infra/main attaches.
        Sid    = "AttachBasicExecutionWithinBoundary"
        Effect = "Allow"
        Action = [
          "iam:AttachRolePolicy",
          "iam:DetachRolePolicy",
        ]
        Resource = "arn:aws:iam::${local.account_id}:role/bgucats-*"
        Condition = {
          StringEquals = {
            "iam:PermissionsBoundary" = aws_iam_policy.lambda_boundary.arn
          }
          ArnEquals = {
            "iam:PolicyARN" = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
          }
        }
      },
      {
        # These don't change what a role may do (the boundary still caps
        # it), and IAM offers no boundary condition on them.
        Sid    = "ManageLambdaRoles"
        Effect = "Allow"
        Action = [
          "iam:DeleteRole",
          "iam:UpdateRole",
          "iam:UpdateRoleDescription",
          "iam:UpdateAssumeRolePolicy",
          "iam:TagRole",
          "iam:UntagRole",
        ]
        Resource = "arn:aws:iam::${local.account_id}:role/bgucats-*"
      },
      {
        Sid      = "PassLambdaRolesToLambda"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = "arn:aws:iam::${local.account_id}:role/bgucats-*"
        Condition = {
          StringEquals = { "iam:PassedToService" = "lambda.amazonaws.com" }
        }
      },
      {
        # Our HTTP API and everything under it (routes, integrations, the
        # authorizer, the stage). apigateway:<verb> is the IAM action for
        # every API Gateway call.
        Sid    = "OurHttpApi"
        Effect = "Allow"
        Action = [
          "apigateway:GET",
          "apigateway:POST",
          "apigateway:PUT",
          "apigateway:PATCH",
          "apigateway:DELETE",
        ]
        # Creating the API is a POST on /apis itself.
        Resource = local.apigateway_arns
      },
    ]
  })
}

# web.tf, site.tf, cognito.tf, ssm.tf.
resource "aws_iam_role_policy" "github_actions_deploy_edge" {
  name = "bgucats-deploy-edge"
  role = aws_iam_role.github_actions_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Create and update, never delete: a distribution's address is the
        # URL people have installed the app from and the poster points at.
        # CreateInvalidation is `make site-invalidate`.
        Sid    = "OurDistributions"
        Effect = "Allow"
        Action = [
          "cloudfront:CreateDistribution",
          "cloudfront:GetDistribution",
          "cloudfront:GetDistributionConfig",
          "cloudfront:UpdateDistribution",
          "cloudfront:CreateInvalidation",
          "cloudfront:GetInvalidation",
          "cloudfront:ListTagsForResource",
          "cloudfront:TagResource",
          "cloudfront:UntagResource",
        ]
        Resource = local.cloudfront_distribution_arns
      },
      {
        Sid    = "OurOriginAccessControls"
        Effect = "Allow"
        Action = [
          "cloudfront:CreateOriginAccessControl",
          "cloudfront:GetOriginAccessControl",
          "cloudfront:GetOriginAccessControlConfig",
          "cloudfront:UpdateOriginAccessControl",
        ]
        Resource = local.cloudfront_oac_arns
      },
      {
        # The AWS-managed cache and origin-request policies the data sources
        # look up by name. Read-only; the List calls have no resource-level
        # scoping.
        Sid    = "ManagedCloudFrontPolicies"
        Effect = "Allow"
        Action = [
          "cloudfront:GetCachePolicy",
          "cloudfront:GetOriginRequestPolicy",
          "cloudfront:ListCachePolicies",
          "cloudfront:ListOriginRequestPolicies",
        ]
        Resource = "*"
      },
      {
        # Our user pool and what hangs off it (client, Google IdP, domain,
        # managed-login branding). No DeleteUserPool, and a deny below.
        Sid    = "OurUserPool"
        Effect = "Allow"
        Action = [
          "cognito-idp:DescribeUserPool",
          "cognito-idp:UpdateUserPool",
          "cognito-idp:GetUserPoolMfaConfig",
          "cognito-idp:SetUserPoolMfaConfig",
          "cognito-idp:ListUserPoolClients",
          "cognito-idp:DescribeUserPoolClient",
          "cognito-idp:CreateUserPoolClient",
          "cognito-idp:UpdateUserPoolClient",
          "cognito-idp:DeleteUserPoolClient",
          "cognito-idp:DescribeIdentityProvider",
          "cognito-idp:CreateIdentityProvider",
          "cognito-idp:UpdateIdentityProvider",
          "cognito-idp:DeleteIdentityProvider",
          "cognito-idp:CreateUserPoolDomain",
          "cognito-idp:UpdateUserPoolDomain",
          "cognito-idp:DeleteUserPoolDomain",
          "cognito-idp:DescribeManagedLoginBranding",
          "cognito-idp:DescribeManagedLoginBrandingByClient",
          "cognito-idp:CreateManagedLoginBranding",
          "cognito-idp:UpdateManagedLoginBranding",
          "cognito-idp:DeleteManagedLoginBranding",
          "cognito-idp:ListTagsForResource",
          "cognito-idp:TagResource",
          "cognito-idp:UntagResource",
        ]
        Resource = local.cognito_user_pool_arns
      },
      {
        # DescribeUserPoolDomain takes a domain name, not a pool, and
        # CreateUserPool has no pool yet: neither has resource-level scoping.
        Sid      = "CreatePoolAndDescribeDomain"
        Effect   = "Allow"
        Action   = ["cognito-idp:CreateUserPool", "cognito-idp:DescribeUserPoolDomain"]
        Resource = "*"
      },
      {
        # The SecureString values come from the production environment's
        # secrets (TF_VAR_*). Encrypting and decrypting them needs no KMS
        # grant here: the AWS-managed aws/ssm key's own policy allows any
        # principal in the account to use it through SSM.
        Sid    = "OurParameters"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:PutParameter",
          "ssm:DeleteParameter",
          "ssm:ListTagsForResource",
          "ssm:AddTagsToResource",
          "ssm:RemoveTagsFromResource",
        ]
        Resource = "arn:aws:ssm:us-east-1:${local.account_id}:parameter/bgucats/*"
      },
      {
        # Metadata only, and no resource-level scoping, like ListAliases.
        Sid      = "DescribeParameters"
        Effect   = "Allow"
        Action   = ["ssm:DescribeParameters", "kms:ListAliases"]
        Resource = "*"
      },
      {
        Sid      = "DescribeSsmKey"
        Effect   = "Allow"
        Action   = "kms:DescribeKey"
        Resource = data.aws_kms_alias.ssm.target_key_arn
      },
    ]
  })
}

# Explicit denies win over any allow, including one a later edit adds by
# mistake. These are the lines that keep the deploy role a deploy role.
resource "aws_iam_role_policy" "github_actions_deploy_guards" {
  name = "bgucats-deploy-guards"
  role = aws_iam_role.github_actions_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Its own role, the CI role, the boundary, the OIDC provider: read,
        # never change. Without this, role/bgucats-* above would include
        # role/bgucats-github-actions-deploy itself.
        Sid       = "NoChangesToTheGuardsThemselves"
        Effect    = "Deny"
        NotAction = ["iam:Get*", "iam:List*"]
        Resource = [
          "arn:aws:iam::${local.account_id}:role/bgucats-github-actions-*",
          aws_iam_policy.lambda_boundary.arn,
          aws_iam_openid_connect_provider.github_actions.arn,
        ]
      },
      {
        # Removing a boundary is never part of a deploy.
        Sid      = "NoBoundaryRemoval"
        Effect   = "Deny"
        Action   = "iam:DeleteRolePermissionsBoundary"
        Resource = "*"
      },
      {
        # The dataset and the state outlive any deploy. Nothing above allows
        # these; the deny keeps it that way whatever a later edit adds.
        Sid    = "NoDeletingStores"
        Effect = "Deny"
        Action = [
          "dynamodb:DeleteTable",
          "dynamodb:DeleteBackup",
          "s3:DeleteBucket",
          "cognito-idp:DeleteUserPool",
        ]
        Resource = "*"
      },
      {
        # People's photos. Terraform owns no object in the media bucket, so
        # a deploy never needs to write, overwrite or delete one.
        Sid    = "NoTouchingTheMedia"
        Effect = "Deny"
        Action = [
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:DeleteObjectVersion",
        ]
        Resource = "arn:aws:s3:::bgucats-media-${local.account_id}/*"
      },
      {
        # The recognition model is published by the owner (docs/deploy.md).
        Sid      = "NoWritesToTheModel"
        Effect   = "Deny"
        Action   = ["s3:PutObject", "s3:DeleteObject"]
        Resource = "arn:aws:s3:::bgucats-admin-web-${local.account_id}/model/*"
      },
    ]
  })
}

output "github_actions_deploy_role_arn" {
  value = aws_iam_role.github_actions_deploy.arn
}
