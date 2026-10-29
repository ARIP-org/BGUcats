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
# This is the union of what the Lambdas use today (infra/main/*.tf): logs,
# the media bucket, the data table, the /bgucats/ parameters. A Lambda that
# needs a new service needs this policy widened first, by the owner, with a
# bootstrap apply, before the PR that uses it can deploy.
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
        Sid    = "DataTableItems"
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
        ]
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
