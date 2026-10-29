# The admin labeling API and the Cognito pre-sign-up trigger. Both ship from
# one zip (`make build-admin`) because they share the allowlist lookup and
# neither is big enough to justify its own dependency set.
data "archive_file" "admin" {
  type        = "zip"
  source_dir  = "${path.module}/../../build/admin"
  output_path = "${path.module}/../../build/admin.zip"
}

resource "aws_iam_role" "admin_lambda" {
  name = "bgucats-admin-lambda"

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

resource "aws_iam_role_policy_attachment" "admin_lambda_logs" {
  role       = aws_iam_role.admin_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "admin_lambda_access" {
  name = "bgucats-admin-lambda-access"
  role = aws_iam_role.admin_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DataTableAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          # The stats page fetches every session in the dataset by ID for
          # its pinned location — a hundred keys per call, not one.
          "dynamodb:BatchGetItem",
          # Shared recognition vectors arrive 25 per call (batch_writer).
          "dynamodb:BatchWriteItem",
          # A blind guess is one transaction whose first step checks the
          # session is still unlabeled; IAM authorizes each step by its own
          # action, so ConditionCheck needs this beside PutItem.
          "dynamodb:ConditionCheckItem",
        ]
        Resource = [
          aws_dynamodb_table.data.arn,
          "${aws_dynamodb_table.data.arn}/index/*",
        ]
      },
      {
        Sid    = "ReadDerivativesForPresigning"
        Effect = "Allow"
        # A presigned URL carries this role's permissions; without GetObject
        # here the URL is generated happily and then 403s in the browser.
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.media.arn}/*"
      },
      {
        Sid    = "HardDeleteRejectedPhotos"
        Effect = "Allow"
        # The bucket is versioned, so removing an object for real means
        # deleting every version of it, not just writing a delete marker.
        Action = [
          "s3:DeleteObject",
          "s3:DeleteObjectVersion",
        ]
        Resource = "${aws_s3_bucket.media.arn}/*"
      },
      {
        Sid    = "SignAppUploads"
        Effect = "Allow"
        # The PWA uploads straight to raw/ with a presigned POST this role
        # signs; the POST is only as good as the signer's own PutObject.
        # raw/ only — the app can never write a derivative or an export.
        # The policy in the POST pins the exact key, type and size.
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.media.arn}/raw/*"
      },
      {
        Sid    = "ListVersionsToDelete"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:ListBucketVersions",
        ]
        Resource = aws_s3_bucket.media.arn
      },
    ]
  })
}

resource "aws_lambda_function" "admin" {
  function_name = "bgucats-admin"
  role          = aws_iam_role.admin_lambda.arn
  handler       = "admin.handler.handler"
  runtime       = "python3.12"
  timeout       = 30
  memory_size   = 512

  filename         = data.archive_file.admin.output_path
  source_code_hash = data.archive_file.admin.output_base64sha256

  environment {
    variables = {
      TABLE_NAME   = aws_dynamodb_table.data.name
      MEDIA_BUCKET = aws_s3_bucket.media.id
    }
  }
}

# Its own role: this one only ever reads a single allowlist item, and a
# trigger that Google can cause to run should not also be able to delete
# photos out of S3.
resource "aws_iam_role" "admin_presignup_lambda" {
  name = "bgucats-admin-presignup-lambda"

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

resource "aws_iam_role_policy_attachment" "admin_presignup_logs" {
  role       = aws_iam_role.admin_presignup_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "admin_presignup_access" {
  name = "bgucats-admin-presignup-access"
  role = aws_iam_role.admin_presignup_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadAllowlist"
        Effect   = "Allow"
        Action   = "dynamodb:GetItem"
        Resource = aws_dynamodb_table.data.arn
      },
    ]
  })
}

resource "aws_lambda_function" "admin_presignup" {
  function_name = "bgucats-admin-presignup"
  role          = aws_iam_role.admin_presignup_lambda.arn
  handler       = "admin.presignup.handler"
  runtime       = "python3.12"
  timeout       = 5
  memory_size   = 128

  filename         = data.archive_file.admin.output_path
  source_code_hash = data.archive_file.admin.output_base64sha256

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.data.name
    }
  }
}

# One catch-all route rather than one per endpoint: the routing table lives in
# src/admin/handler.py where it can be read in one screen.
resource "aws_apigatewayv2_integration" "admin" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.admin.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.main.id
  name             = "bgucats-cognito"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.web.id]
    issuer   = "https://${aws_cognito_user_pool.admins.endpoint}"
  }
}

resource "aws_apigatewayv2_route" "admin_api" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "ANY /api/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.admin.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_lambda_permission" "apigw_admin" {
  statement_id  = "AllowAPIGatewayInvokeAdmin"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.admin.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}
