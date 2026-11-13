# The admin labeling API and the Cognito pre-sign-up trigger. Both ship from
# one zip (`make build-admin`) because they share the allowlist lookup and
# neither is big enough to justify its own dependency set.
data "archive_file" "admin" {
  type        = "zip"
  source_dir  = "${path.module}/../../build/admin"
  output_path = "${path.module}/../../build/admin.zip"
}

resource "aws_iam_role" "admin_lambda" {
  name                 = "bgucats-admin-lambda"
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
        Sid    = "EncountersInTheApp"
        Effect = "Allow"
        # Since B3b: a pick and a label keep the person's encounter item in
        # the app's table (docs/data-model.md, "ENC"). It finds the person
        # by their sign-in. Since B6: the new-cat proposals' queue
        # (PROPOSALS#{status} on GSI2) and deciding one (PROPOSAL#{id}).
        # Since B4b: a cat's name poll (CAT#{id}), to read it, mark an
        # option removed and lock the shown name. Since B8b: the reports
        # queue (REPORTS#{status} on GSI2), answering a report (REPORT#{id})
        # and marking a post for the events Lambda to hide, put back or
        # remove (POST#{id}). Since B8c: the list of the app's people
        # (ENTITY#USER on GSI2); a ban is a mark on a USER# item, which
        # was already allowed. Nothing else there.
        Action = [
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query",
        ]
        Resource = [
          aws_dynamodb_table.social.arn,
          "${aws_dynamodb_table.social.arn}/index/GSI2",
        ]
        Condition = {
          "ForAllValues:StringLike" = {
            "dynamodb:LeadingKeys" = ["IDENTITY#*", "USER#*", "PROPOSAL#*", "PROPOSALS#*", "CAT#*", "REPORT#*", "REPORTS#*", "POST#*", "ENTITY#USER"]
          }
        }
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
      TABLE_NAME        = aws_dynamodb_table.data.name
      MEDIA_BUCKET      = aws_s3_bucket.media.id
      SIGNUP_POLICY     = local.settings.signup_policy
      SIGNUP_DOMAINS    = join(",", local.signup_domains)
      SOCIAL            = local.settings.social ? "on" : "off"
      SOCIAL_TABLE_NAME = aws_dynamodb_table.social.name
    }
  }
}

# Its own role: this one only ever reads a single allowlist item, and a
# trigger that Google can cause to run should not also be able to delete
# photos out of S3.
resource "aws_iam_role" "admin_presignup_lambda" {
  name                 = "bgucats-admin-presignup-lambda"
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
      TABLE_NAME     = aws_dynamodb_table.data.name
      SIGNUP_POLICY  = local.settings.signup_policy
      SIGNUP_DOMAINS = join(",", local.signup_domains)
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

# The iPhone app's preflight. Its pages are at capacitor://localhost, so a
# call to the API is cross-origin and the web view first sends an OPTIONS
# that carries no token. `ANY` above matches OPTIONS too, and its authorizer
# answered that preflight 401, before the CORS configuration (api.tf) could;
# the web view then refused the real call, which an iPhone shows as "Load
# failed". A more specific method wins, so this route takes every OPTIONS.
# API Gateway does not answer it by itself: it invokes the Lambda and adds
# the CORS headers to its answer, so the handler answers a preflight 204
# before anything else (`preflight` in src/common/api.py). Found on
# 2026-11-11, the first TestFlight build's first sign-in; the Lambda's half
# on 2026-11-13, when the route alone had only changed whose 401 it was.
resource "aws_apigatewayv2_route" "admin_api_preflight" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "OPTIONS /api/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.admin.id}"
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "apigw_admin" {
  statement_id  = "AllowAPIGatewayInvokeAdmin"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.admin.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}
