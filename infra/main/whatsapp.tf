# The WhatsApp bot: a second Lambda on the same ingest package, behind the
# same HTTP API, writing to the same table and bucket. A separate function
# rather than a branch inside the Telegram one, so each holds only its own
# platform's secrets and either can be switched off without touching the
# other.

resource "aws_iam_role" "whatsapp_lambda" {
  name                 = "bgucats-whatsapp-lambda"
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

resource "aws_iam_role_policy_attachment" "whatsapp_lambda_logs" {
  role       = aws_iam_role.whatsapp_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# The ingest Lambda's grants, with WhatsApp's secrets in place of
# Telegram's. The salt is shared: one submitter-hash scheme for the table.
resource "aws_iam_role_policy" "whatsapp_lambda_access" {
  name = "bgucats-whatsapp-lambda-access"
  role = aws_iam_role.whatsapp_lambda.id

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
          # Done deletes the ACTIVE_SESSION pointer, and a session opened
          # in a lost race is deleted while still empty.
          "dynamodb:DeleteItem",
        ]
        Resource = aws_dynamodb_table.data.arn
      },
      {
        Sid    = "ReadSecrets"
        Effect = "Allow"
        Action = "ssm:GetParameters"
        Resource = concat(
          [for p in aws_ssm_parameter.whatsapp : p.arn],
          [aws_ssm_parameter.submitter_hash_salt.arn],
        )
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

resource "aws_lambda_function" "whatsapp" {
  function_name = "bgucats-whatsapp"
  role          = aws_iam_role.whatsapp_lambda.arn
  handler       = "ingest.whatsapp.handler"
  runtime       = "python3.12"
  # Two hops per media file (ID -> URL -> bytes) rather than Telegram's one.
  timeout     = 15
  memory_size = 256

  filename         = data.archive_file.ingest.output_path
  source_code_hash = data.archive_file.ingest.output_base64sha256

  environment {
    variables = {
      TABLE_NAME                  = aws_dynamodb_table.data.name
      MEDIA_BUCKET                = aws_s3_bucket.media.id
      SUBMITTER_HASH_SALT_PARAM   = aws_ssm_parameter.submitter_hash_salt.name
      WHATSAPP_ACCESS_TOKEN_PARAM = aws_ssm_parameter.whatsapp["access-token"].name
      WHATSAPP_APP_SECRET_PARAM   = aws_ssm_parameter.whatsapp["app-secret"].name
      WHATSAPP_VERIFY_TOKEN_PARAM = aws_ssm_parameter.whatsapp["verify-token"].name
      GRAPH_API_VERSION           = "v26.0"
    }
  }
}

resource "aws_apigatewayv2_integration" "whatsapp" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.whatsapp.invoke_arn
  payload_format_version = "2.0"
}

# GET is Meta's one-time subscription handshake; POST is every message.
resource "aws_apigatewayv2_route" "whatsapp_webhook" {
  for_each = toset(["GET", "POST"])

  api_id    = aws_apigatewayv2_api.main.id
  route_key = "${each.key} /webhook/whatsapp"
  target    = "integrations/${aws_apigatewayv2_integration.whatsapp.id}"
}

resource "aws_lambda_permission" "apigw_whatsapp" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.whatsapp.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*/webhook/whatsapp"
}

output "whatsapp_webhook_url" {
  description = "Callback URL for the Meta dashboard (WhatsApp > Configuration)."
  value       = "${aws_apigatewayv2_api.main.api_endpoint}/webhook/whatsapp"
}

output "whatsapp_lambda_name" {
  value = aws_lambda_function.whatsapp.function_name
}
