# The ceiling on every role infra/main creates.
#
# The deploy role has to create and edit IAM roles: each Lambda has its own.
# Without a limit, that is the same as being an administrator: write a role
# with AdministratorAccess, then use it. So the deploy role may only create
# or change a bgucats-* role that carries this boundary (deploy_role.tf), and
# a role's effective permissions are the intersection of its own policies
# and this one. Whatever a pull request writes into a Lambda's policy, it
# gets no more than what is below.
#
# This is the union of what the Lambdas use (infra/main/*.tf): logs, the
# media bucket, the two tables, the /bgucats/ parameters. Since 2026-11-12
# it also holds what the app plan's Lambdas will need, widened once ahead of
# them (docs/app-plan/02-architecture.md, "What the guardrails must
# learn"): the social table's stream, publishing to the alerts topic, and
# deleting a person's sign-in. A Lambda gets none of these until its own
# role in infra/main grants them. A Lambda that needs anything else needs
# this policy widened first, by the owner, with a bootstrap apply, before
# the PR that uses it can deploy.
resource "aws_iam_policy" "lambda_boundary" {
  name        = "bgucats-lambda-permissions-boundary"
  description = "Permissions boundary for every role in infra/main. Applied by the owner only."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # What AWSLambdaBasicExecutionRole grants, cut down to our log groups.
        # PutLogEvents is authorized on the stream's own ARN, so list both forms.
        Sid    = "OwnLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = [
          "arn:aws:logs:us-east-1:${local.account_id}:log-group:/aws/lambda/bgucats-*",
          "arn:aws:logs:us-east-1:${local.account_id}:log-group:/aws/lambda/bgucats-*:log-stream:*",
        ]
      },
      {
        Sid    = "MediaObjects"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:DeleteObjectVersion",
        ]
        Resource = "arn:aws:s3:::bgucats-media-${local.account_id}/*"
      },
      {
        Sid    = "ListMedia"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:ListBucketVersions",
        ]
        Resource = "arn:aws:s3:::bgucats-media-${local.account_id}"
      },
      {
        # Items of both tables: the dataset and, from the app plan
        # (docs/app-plan/), the social table. Which Lambda may touch which
        # table is its own role's policy in infra/main; this is the ceiling.
        Sid    = "TableItems"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:BatchGetItem",
          "dynamodb:BatchWriteItem",
          "dynamodb:ConditionCheckItem",
        ]
        Resource = [
          local.data_table_arn,
          "${local.data_table_arn}/index/*",
          local.social_table_arn,
          "${local.social_table_arn}/index/*",
        ]
      },
      {
        # The events Lambda is fed the social table's changes by an event
        # source mapping, which reads the stream as the function's role.
        Sid    = "SocialTableStream"
        Effect = "Allow"
        Action = [
          "dynamodb:DescribeStream",
          "dynamodb:GetRecords",
          "dynamodb:GetShardIterator",
        ]
        Resource = "${local.social_table_arn}/stream/*"
      },
      {
        # No resource-level scoping. It lists stream names, nothing more.
        Sid      = "ListStreams"
        Effect   = "Allow"
        Action   = "dynamodb:ListStreams"
        Resource = "*"
      },
      {
        # A stream record that keeps failing is sent to the alerts topic,
        # as the function's role, and a report emails the admins.
        Sid      = "PublishToAlerts"
        Effect   = "Allow"
        Action   = "sns:Publish"
        Resource = local.alerts_topic_arn
      },
      {
        # Deleting an account signs the person out and removes their
        # sign-in (docs/app-plan/03-data-model.md, "Deleting an account").
        Sid    = "DeleteAppUsers"
        Effect = "Allow"
        Action = [
          "cognito-idp:AdminUserGlobalSignOut",
          "cognito-idp:AdminDeleteUser",
        ]
        Resource = local.cognito_user_pool_arns
      },
      {
        Sid    = "OwnSecrets"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
        ]
        Resource = "arn:aws:ssm:us-east-1:${local.account_id}:parameter/bgucats/*"
      },
      {
        Sid      = "DecryptOwnSecrets"
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = data.aws_kms_alias.ssm.target_key_arn
      },
    ]
  })
}

output "lambda_permissions_boundary_arn" {
  value = aws_iam_policy.lambda_boundary.arn
}
