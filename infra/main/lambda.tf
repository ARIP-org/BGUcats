# Packaged by `make build-ingest` (pip install -t build/ingest, then copy
# handler.py in) so the zip only ever contains what the Lambda actually
# needs — no Pillow/ImageHash, those belong to the process Lambda.
data "archive_file" "ingest" {
  type        = "zip"
  source_dir  = "${path.module}/../../build/ingest"
  output_path = "${path.module}/../../build/ingest.zip"
}

resource "aws_iam_role" "ingest_lambda" {
  name = "bgucats-ingest-lambda"

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
  role       = aws_iam_role.ingest_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Scoped to exactly what this function touches — the media bucket's raw/
# prefix, the data table, and its own three secrets. Extend when this
# Lambda takes on new responsibilities, never ahead of time.
resource "aws_iam_role_policy" "ingest_lambda_access" {
  name = "bgucats-ingest-lambda-access"
  role = aws_iam_role.ingest_lambda.id

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
        Action = "ssm:GetParameters"
        Resource = [
          aws_ssm_parameter.telegram_bot_token.arn,
          aws_ssm_parameter.telegram_webhook_secret.arn,
          aws_ssm_parameter.submitter_hash_salt.arn,
        ]
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
  function_name = "bgucats-ingest"
  role          = aws_iam_role.ingest_lambda.arn
  handler       = "handler.handler"
  runtime       = "python3.12"
  timeout       = 10
  memory_size   = 256

  filename         = data.archive_file.ingest.output_path
  source_code_hash = data.archive_file.ingest.output_base64sha256

  environment {
    variables = {
      TABLE_NAME                    = aws_dynamodb_table.data.name
      MEDIA_BUCKET                  = aws_s3_bucket.media.id
      TELEGRAM_BOT_TOKEN_PARAM      = aws_ssm_parameter.telegram_bot_token.name
      TELEGRAM_WEBHOOK_SECRET_PARAM = aws_ssm_parameter.telegram_webhook_secret.name
      SUBMITTER_HASH_SALT_PARAM     = aws_ssm_parameter.submitter_hash_salt.name
    }
  }
}

output "ingest_lambda_name" {
  value = aws_lambda_function.ingest.function_name
}
