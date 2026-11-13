# The member API: everything a user does in the app that is not an upload
# (docs/app-plan/04-api.md), behind ANY /api/v1/{proxy+}. Milestone F4.
#
# Its own Lambda and its own role, apart from the desk's API (admin_api.tf),
# because that one can delete photos and merge sessions. This one can read
# the dataset and never write it (tests/app/test_app_role.py holds that),
# and writes only bgucats-social.
#
# With settings.social false (production until the app opens), every route
# answers 404.

data "archive_file" "app" {
  type        = "zip"
  source_dir  = "${path.module}/../../build/app"
  output_path = "${path.module}/../../build/app.zip"
}

resource "aws_iam_role" "app_lambda" {
  name                 = "bgucats-app-lambda"
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

resource "aws_iam_role_policy_attachment" "app_lambda_logs" {
  role       = aws_iam_role.app_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "app_lambda_access" {
  name = "bgucats-app-lambda-access"
  role = aws_iam_role.app_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # The allowlist and, from B2, the cats and photos. Reading only.
        Sid    = "ReadTheDataset"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:BatchGetItem",
        ]
        Resource = [
          aws_dynamodb_table.data.arn,
          "${aws_dynamodb_table.data.arn}/index/*",
        ]
      },
      {
        # Signing addresses for photos' thumbnails and mediums (B2). Only
        # the derivatives: never an original, never a write.
        Sid      = "SignDerivatives"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.media.arn}/derived/*"
      },
      {
        # Accounts, and everything people do in the app.
        Sid    = "SocialItems"
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
          aws_dynamodb_table.social.arn,
          "${aws_dynamodb_table.social.arn}/index/*",
        ]
      },
    ]
  })
}

resource "aws_lambda_function" "app" {
  function_name = "bgucats-app"
  role          = aws_iam_role.app_lambda.arn
  handler       = "app.handler.handler"
  runtime       = "python3.12"
  timeout       = 15
  memory_size   = 512

  filename         = data.archive_file.app.output_path
  source_code_hash = data.archive_file.app.output_base64sha256

  environment {
    variables = {
      DATA_TABLE_NAME   = aws_dynamodb_table.data.name
      SOCIAL_TABLE_NAME = aws_dynamodb_table.social.name
      MEDIA_BUCKET      = aws_s3_bucket.media.id
      SOCIAL            = local.settings.social ? "on" : "off"
      SIGNUP_POLICY     = local.settings.signup_policy
      SIGNUP_DOMAINS    = join(",", local.signup_domains)
      TERMS_VERSION     = local.terms_version
      FLAGS             = jsonencode(local.app_flags)
    }
  }
}

resource "aws_apigatewayv2_integration" "app" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.app.invoke_arn
  payload_format_version = "2.0"
}

# More specific than ANY /api/{proxy+}, so API Gateway sends /api/v1/...
# here and everything else to the desk's API.
resource "aws_apigatewayv2_route" "app_api" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "ANY /api/v1/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.app.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

# A preflight carries no token, so it must not meet the authorizer: on the
# ANY route it got 401 and the iPhone app's calls failed with "Load failed"
# (docs/notes.md, "The iPhone app"). The Lambda answers it 204
# (`preflight` in src/common/api.py) and API Gateway adds the CORS headers.
resource "aws_apigatewayv2_route" "app_api_preflight" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "OPTIONS /api/v1/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.app.id}"
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "apigw_app" {
  statement_id  = "AllowAPIGatewayInvokeApp"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.app.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}
