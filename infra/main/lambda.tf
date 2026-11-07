# Packaged by `make build-ingest` (pip install -t build/ingest, then copy
# the ingest package in) so the zip only ever contains what the Lambda
# actually needs — no Pillow/ImageHash, those belong to the process Lambda.
data "archive_file" "ingest" {
  count       = local.telegram_bot_count
  type        = "zip"
  source_dir  = "${path.module}/../../build/ingest"
  output_path = "${path.module}/../../build/ingest.zip"
}

resource "aws_iam_role" "ingest_lambda" {
  count                = local.telegram_bot_count
  name                 = "bgucats-ingest-lambda"
  permissions_boundary = local.lambda_permissions_boundary

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "sts:AssumeRole"
        Principal = { Service = "lambda.amazonaws.com" }
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ingest_lambda_logs" {
  count      = local.telegram_bot_count
  role       = aws_iam_role.ingest_lambda[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Scoped to exactly what this function touches — the media bucket's raw/
# prefix, the data table, and its own three secrets. Extend when this
# Lambda takes on new responsibilities, never ahead of time.
resource "aws_iam_role_policy" "ingest_lambda_access" {
  count = local.telegram_bot_count
  name  = "bgucats-ingest-lambda-access"
  role  = aws_iam_role.ingest_lambda[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "WriteRawPhotos"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.media.arn}/raw/*"
      },
      {
        Sid    = "DataTableAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          # Closing a session deletes the submitter's ACTIVE_SESSION
          # pointer; the Session record itself is never deleted.
          "dynamodb:DeleteItem",
        ]
        Resource = aws_dynamodb_table.data.arn
      },
      {
        Sid    = "ReadSecrets"
        Effect = "Allow"
        # Handler uses the batch API (ssm.get_parameters, plural) to fetch
        # all three in one call — GetParameter (singular) is a different
        # IAM action and doesn't cover it.
        Action   = "ssm:GetParameters"
        Resource = local.ssm_param_arns
      },
      {
        Sid      = "DecryptSecrets"
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = data.aws_kms_alias.ssm.target_key_arn
      },
    ]
  })
}

resource "aws_lambda_function" "ingest" {
  count         = local.telegram_bot_count
  function_name = "bgucats-ingest"
  role          = aws_iam_role.ingest_lambda[0].arn
  handler       = "ingest.handler.handler"
  runtime       = "python3.12"
  timeout       = 10
  memory_size   = 256

  filename         = data.archive_file.ingest[0].output_path
  source_code_hash = data.archive_file.ingest[0].output_base64sha256

  environment {
    variables = {
      TABLE_NAME                    = aws_dynamodb_table.data.name
      MEDIA_BUCKET                  = aws_s3_bucket.media.id
      TELEGRAM_BOT_TOKEN_PARAM      = local.ssm_params.telegram_bot_token
      TELEGRAM_WEBHOOK_SECRET_PARAM = local.ssm_params.telegram_webhook_secret
      SUBMITTER_HASH_SALT_PARAM     = local.ssm_params.submitter_hash_salt
      # Opened as a Telegram Mini App from the bot's "Pick on map" button.
      # Telegram only accepts https Mini App URLs, which CloudFront gives us.
      MAP_PICKER_URL = "https://${aws_cloudfront_distribution.site.domain_name}/map.html"
    }
  }
}

# null in staging, which has no bot.
output "ingest_lambda_name" {
  value = one(aws_lambda_function.ingest[*].function_name)
}

# The bot's resources took a count on 2026-11-07, when staging (no bot)
# arrived. These keep production's from being destroyed and recreated.
moved {
  from = aws_iam_role.ingest_lambda
  to   = aws_iam_role.ingest_lambda[0]
}

moved {
  from = aws_iam_role_policy_attachment.ingest_lambda_logs
  to   = aws_iam_role_policy_attachment.ingest_lambda_logs[0]
}

moved {
  from = aws_iam_role_policy.ingest_lambda_access
  to   = aws_iam_role_policy.ingest_lambda_access[0]
}

moved {
  from = aws_lambda_function.ingest
  to   = aws_lambda_function.ingest[0]
}
